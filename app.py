import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from io import BytesIO
from db import get_db, initialize_db

app = Flask(__name__)
app.secret_key = 'your_secret_key'

initialize_db()

@app.route('/')
def index():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name, specialization, experience FROM doctors")
    doctors = cursor.fetchall()
    conn.close()
    return render_template('index.html', doctors=doctors)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT doctor_id, password FROM doctor_logins WHERE username = ?", (username,))
        doc = cursor.fetchone()
        if doc and check_password_hash(doc[1], password):
            session['user_id'] = doc[0]
            session['username'] = username
            session['role'] = 'doctor'
            return redirect('/doctor')

        cursor.execute("SELECT patient_id, password FROM patient_logins WHERE username = ?", (username,))
        pat = cursor.fetchone()
        if pat and check_password_hash(pat[1], password):
            session['user_id'] = pat[0]
            session['username'] = username
            session['role'] = 'patient'
            return redirect('/user')
        # check labadmin if not found in users
        cursor.execute("SELECT id, username, password FROM lab_admins WHERE username = ?", (username,))
        labadmin = cursor.fetchone()

        if labadmin and check_password_hash(labadmin[2], password):
            session['user_id'] = labadmin[0]
            session['username'] = labadmin[1]
            session['role'] = 'labadmin'
            return redirect('/labadmin')
        #for admin
        cursor.execute("SELECT id, password FROM admin WHERE username = ?", (username,))
        admin = cursor.fetchone()
        if admin and check_password_hash(admin[1], password):  # Password check here
            session['admin'] = admin[0]
            return redirect('/admin/dashboard')
        
        conn.close()
        flash("Invalid credentials.")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

def fetch_grouped_records():
    conn = get_db()  # Or sqlite3.connect(...) if you're not using get_db()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT p.id as patient_id, p.name, p.age, p.gender, p.contact, p.username,
               mr.id, mr.scan_and_report, mr.normal_report, mr.upload_date
        FROM patients p
        LEFT JOIN medical_records mr ON p.username = mr.username
        ORDER BY p.id
    """)
    rows = cursor.fetchall()
    conn.close()

    patients = {}
    for row in rows:
        username = row["username"]
        if username not in patients:
            patients[username] = {
                "id": row["patient_id"],
                "name": row["name"],
                "age": row["age"],
                "gender": row["gender"],
                "contact": row["contact"],
                "username": username,
                "records": []
            }
        if row["scan_and_report"] or row["normal_report"]:
            patients[username]["records"].append({
                "id": row["id"],
                "scan_and_report": row["scan_and_report"],
                "normal_report": row["normal_report"],
                "upload_date": row["upload_date"]
            })

    return patients


@app.route('/doctor', methods=['GET', 'POST'])
def doctor_dashboard():
    if 'role' in session and session['role'] == 'doctor':
        return render_template('doctor_dashboard.html')
    flash("Unauthorized access. Please login.")    
    return redirect('/login')
@app.route('/doctor/doctor_view_patient', methods=['GET', 'POST'])
def doctor_view_patient():
    if 'role' not in session or session['role'] != 'doctor':        
        flash("Unauthorized access. Please login.")    
        return redirect('/login')

    if request.method == 'GET':
        return redirect(url_for('doctor_dashboard'))  # or render search page

    username = request.form.get('username')  # safe access
    if not username:
        flash("No username provided.")
        return redirect(url_for('doctor_dashboard'))

    conn = get_db()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM patients WHERE username = ? OR name = ?", (username, username))
    patient = cursor.fetchone()

    if not patient:
        conn.close()
        flash("Patient not found.")
        return redirect(url_for('doctor_dashboard'))

    cursor.execute("""
        SELECT username, scan_and_report, normal_report, upload_date 
        FROM medical_records 
        WHERE username = ?
    """, (patient['username'],))
    
    records = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return render_template('doctor_view_patient.html', patient=patient, records=records)


@app.route('/doctor/doctor_view_medical_record')
def doctor_view_medical_record():
    if 'role' in session and session['role'] == 'doctor':
        patients = fetch_grouped_records()
        return render_template("doctor_view_medical_record.html", patients=patients)
    flash("Unauthorized access. Please login.")
    return redirect("/login")


@app.route('/doctor/appointments')
def view_appointments():
    if 'role' in session and session['role'] == 'doctor':
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM appointments WHERE doctor_id = ?", (session['user_id'],))
        appointments = cursor.fetchall()
        conn.close()
        return render_template('view_appointments.html', appointments=appointments)
    flash("Unauthorized access. Please login.")
    return redirect('/login')

@app.route('/user')
def user_dashboard():
    if 'role' in session and session['role'] == 'patient':
        return render_template('user_dashboard.html')
    flash("Unauthorized access. Please login.")
    return redirect('/login')

@app.route('/user/book', methods=['GET', 'POST'])
def book_appointment():
    conn = get_db()
    cursor = conn.cursor()
    if request.method == 'POST':
        doctor_id = request.form['doctor_id']
        date = request.form['date']
        cursor.execute("INSERT INTO appointments (patient_id, doctor_id, date, status) VALUES (?, ?, ?, 'Pending')",
                       (session['user_id'], doctor_id, date))
        cursor.execute("UPDATE doctors SET available_slots = available_slots - 1 WHERE id = ?", (doctor_id,))
        conn.commit()
        conn.close()
        flash("Appointment booked successfully.")
        return redirect('/user')
    else:
        cursor.execute("SELECT id, name, specialization, available_slots FROM doctors WHERE available_slots > 0")
        doctors = cursor.fetchall()
        conn.close()
        return render_template('book_appointment.html', doctors=doctors)
    

@app.route('/user/records')
def view_user_records():
    if 'role' in session and session['role'] == 'patient':
        username = session['username']  # Assuming the username is stored in session
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, username, scan_and_report, normal_report, upload_date 
                FROM medical_records 
                WHERE username = ?
            """, (username,))
            records = cursor.fetchall()
            
            # Format the records into a list of dictionaries
            records = [
                {
                    'id': row[0],  # Adding the ID field to the record
                    'username': row[1],
                    'scan_and_report': row[2],
                    'normal_report': row[3],
                    'upload_date': row[4]
                }
                for row in records
            ]
        
        # Return the user_medical_records.html template with records
        return render_template('user_medical_records.html', records=records)
    flash("Unauthorized access. Please login.")    
    return redirect('/login')  # Redirect if user is not logged in or not a patient



@app.route('/admin')
def admin():
    if 'role' in session and session['role'] == 'admin':
        return render_template('admin_dashboard.html')
    flash("Unauthorized access. Please login.")
    return redirect('/login')

@app.route('/admin/dashboard')
def admin_dashboard():
    if 'admin' in session:
        return render_template('admin_dashboard.html')
    flash("Unauthorized access. Please login to view.")
    return redirect('/login')

@app.route('/admin/add_doctor_form')
def add_doctor_form():
    if 'admin' in session:
        return render_template('add_doctor.html')
    flash("Unauthorized access. Please login to view.")
    return redirect('/login')

@app.route('/admin/add_patient_form')
def add_patient_form():
    if 'admin' in session:
        return render_template('add_patient.html')
    flash("Unauthorized access. Please login to view.")
    return redirect('/login')

@app.route('/admin/add_labadmin_form')
def add_labadmin_form():
    if 'admin' in session:
        return render_template('add_labadmin.html')
    flash("Unauthorized access. Please login to view.")
    return redirect('/login')
@app.route('/admin/add_doctor', methods=['GET', 'POST'])
def add_doctor():
    if 'admin' in session:
        data = request.form
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO doctors (name, gender, specialization, experience, contact, available_slots)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    data['name'],
                    data['gender'],  # Added gender field
                    data['specialization'],
                    data['experience'],
                    data['contact'],
                    data['slots']
                ))
                doctor_id = cursor.lastrowid
                password_hash = generate_password_hash(data['password'])
                cursor.execute("""
                    INSERT INTO doctor_logins (doctor_id, username, password)
                    VALUES (?, ?, ?)
                """, (doctor_id, data['username'], password_hash))
                flash("Doctor added successfully")
        except sqlite3.IntegrityError:
            flash("Username already exists or data invalid.")
        return redirect('/admin/dashboard')
    flash("Unauthorized access. Please login to view.")
    return redirect('/login')


@app.route('/admin/add_patient', methods=['GET','POST'])
def add_patient():
    if 'admin' in session:
        data = request.form
        try:
            with get_db() as conn:
                cursor = conn.cursor()

                # Check if username already exists in patients table
                cursor.execute("SELECT 1 FROM patients WHERE username = ?", (data['username'],))
                if cursor.fetchone():
                    flash("Username already exists. Please choose a different one.")
                    return redirect('/admin/dashboard')

                # Insert into patients table (including username now)
                cursor.execute("""
                    INSERT INTO patients (name, age, gender, contact, username)
                    VALUES (?, ?, ?, ?, ?)
                """, (data['name'], data['age'], data['gender'], data['contact'], data['username']))
                
                patient_id = cursor.lastrowid

                # Insert into patient_logins table
                password_hash = generate_password_hash(data['password'])
                cursor.execute("""
                    INSERT INTO patient_logins (patient_id, username, password)
                    VALUES (?, ?, ?)
                """, (patient_id, data['username'], password_hash))

                flash("Patient added successfully")
        except sqlite3.IntegrityError:
            flash("Username already exists or data invalid.")
        return redirect('/admin/dashboard')
    flash("Unauthorized access. Please login to view.")
    return redirect('/login')


@app.route('/admin/add_labadmin', methods=['GET', 'POST'])
def add_labadmin():
    if 'admin' in session:
        if request.method == 'POST':
            data = request.form
            try:
                with get_db() as conn:
                    cursor = conn.cursor()
                    hashed_password = generate_password_hash(data['password'])

                    # Insert into lab_admins
                    cursor.execute("""
                        INSERT INTO lab_admins (name, specialization, phone, username, password)
                        VALUES (?, ?, ?, ?, ?)
                    """, (data['name'], data['specialization'], data['phone'], data['username'], hashed_password))

                    labadmin_id = cursor.lastrowid  # Get the ID of the inserted lab admin

                    # Insert into labadmin_logins
                    cursor.execute("""
                        INSERT INTO labadmin_logins (labadmin_id, username, password)
                        VALUES (?, ?, ?)
                    """, (labadmin_id, data['username'], hashed_password))

                    flash("Lab Admin added successfully.")
            except sqlite3.IntegrityError as e:
                flash("Username already exists or data is invalid.")
            return redirect('/admin/dashboard')
        return render_template('add_labadmin.html')
    flash("Unauthorized access. Please login to view.")
    return redirect('/login')

@app.route('/admin/view_doctors')
def view_doctors():
    if 'admin' in session:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT d.*, l.username FROM doctors d
            JOIN doctor_logins l ON d.id = l.doctor_id
        """)
        doctors = cursor.fetchall()
        conn.close()
        return render_template('view_doctors.html', doctors=doctors)
    flash("Unauthorized access. Please login to view.")
    return redirect('/login')

@app.route('/admin/view_patients')
def view_patients():
    if 'admin' in session:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.*, l.username FROM patients p
            JOIN patient_logins l ON p.id = l.patient_id
        """)
        patients = cursor.fetchall()
        conn.close()
        return render_template('view_patients.html', patients=patients)
    flash("Unauthorized access. Please login to view.")
    return redirect('/login')

@app.route('/admin/view_labadmins')
def view_labadmins():
    if 'admin' not in session:
        flash("Unauthorized access. Please login to view.")
        return redirect('/login')

    conn = get_db()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT l.id, l.name, l.specialization, l.phone, log.username 
        FROM lab_admins l
        JOIN labadmin_logins log ON l.id = log.labadmin_id
    """)  
    labadmins = cursor.fetchall()

    return render_template('view_labadmins.html', labadmins=labadmins)

@app.route('/admin/medical-records')
def view_medical_records():
    if 'admin' in session:
        patients = fetch_grouped_records()
        return render_template("medical_records.html", patients=patients)
    flash("Unauthorized access. Please login to view.")
    return redirect('/login')



@app.route('/admin/change_password', methods=['GET','POST'])
def change_admin_password():
    if 'admin' not in session:
        flash("Unauthorized access. Please login to view.")
        return redirect('/admin/dashboard')
    
    new_password = generate_password_hash(request.form['new_password'])
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE admin SET password = ? WHERE username = 'admin'", (new_password,))
    conn.commit()
    conn.close()
    flash("Password updated.")
    
    return redirect('/admin/dashboard')

@app.route('/labadmin', methods=['GET', 'POST'])
def labadmin_dashboard():
    if 'role' in session and session['role'] == 'labadmin':
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM patients")
        patients = cursor.fetchall()
        conn.close()
        return render_template('labadmin_dashboard.html', patients=patients)
    flash("Unauthorized access. Please login.")
    return redirect('/login')

@app.route('/labadmin/upload', methods=['GET', 'POST'])
def upload_medical_history():
    if 'role' in session and session['role'] == 'labadmin':
        if request.method == 'POST':
            username = request.form['username']
            scan_and_report = request.form['scan_and_report']
            normal_report = request.form['normal_report']
            upload_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            with get_db() as conn:
                cursor = conn.cursor()
                # Check if the username exists in the patients table
                cursor.execute("SELECT id FROM patients WHERE username = ?", (username,))
                result = cursor.fetchone()

                if result:
                    cursor.execute("""
                        INSERT INTO medical_records (username, scan_and_report, normal_report, upload_date)
                        VALUES (?, ?, ?, ?)
                    """, (username, scan_and_report, normal_report, upload_date))
                    flash("Medical history uploaded successfully.")
                else:
                    flash("Patient username not found.")

            return redirect('/labadmin/upload')

        return render_template('upload_medical_history.html')
    flash("Unauthorized access. Please login.")
    return redirect('/login')

  
@app.route('/labadmin/view_patients')
def labadmin_view_patients():
    if 'role' in session and session['role'] == 'labadmin':
        patients = fetch_grouped_records()
        return render_template("labadmin_view_patients.html", patients=patients)
    flash("Unauthorized access. Please login.")
    return redirect("/login")



if __name__ == '__main__':
    app.run(debug=True, threaded=False)
