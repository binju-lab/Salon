from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date, time, timedelta

from sqlalchemy import select

from models import Appointment,User

from tests.test_staff import TEST_DATA


# Role D: Ruizhe Zheng 24107708
# 员工页面后端代码
staff = Blueprint("staff", __name__, url_prefix='/staff')
db = SQLAlchemy()

query_date = date.today()
def getUser():
    return TEST_DATA["users"][2]
stylist = getUser()
def getAppointments():
    return [TEST_DATA["appointments"][0],TEST_DATA["appointments"][1]]
appointments=getAppointments()

# def getUser():
#     return (
#         db.session.query(User)
#         .filter_by(role="stylist")
#         .order_by(User.id)
#         .first()
#     )
# def _user_id(stylist):
#     return stylist.id if isinstance(stylist, User) else stylist
# def getAppointments(stylist, date):
#     day = date.date() if isinstance(date, datetime) else date
#     day_start = datetime.combine(day, time.min)
#     day_end = day_start + timedelta(days=1)
#     return (
#         db.session.query(Appointment)
#         .filter(Appointment.stylist_id == _user_id(stylist))
#         .filter(Appointment.starts_at >= day_start)
#         .filter(Appointment.starts_at < day_end)
#         .order_by(Appointment.starts_at)
#         .all()
#     )

# 登录到员工页面，主页 http://127.0.0.1:5000/staff/schedule
@staff.get('/schedule')
def stylist_day():
    # user: 当前登录用户
    # scheduleDay: 包含指定用户当日预约的列表
    return render_template(
        'staff/stylistDay.html',
        user=stylist,
        scheduleDay=appointments
    )

@staff.post("/stylist/appointments/<id>/complete")
def complete_appointment(id):
    # appt = Appointment.query.get(int(id))
    appt = findAppointmentById(appointments,int(id))
    if appt is None:
        return jsonify(error="not found"), 404
 
    appt.state = "completed"
    # db.session.commit()                            

    return jsonify({
    "id": appt.id,
    "state": appt.state})

@staff.post("/stylist/appointments/<id>/cancel")
def cancel_appointment(id):
    # appt = Appointment.query.get(int(id))
    appt = findAppointmentById(appointments,int(id))
    if appt is None:
        return jsonify(error="not found"), 404
 
    appt.state = "canceled"
    # db.session.commit()                            
 
    return jsonify({
    "id": appt.id,
    "state": appt.state})

@staff.post("/stylist/appointments/<id>/noshow")
def noshow_appointment(id):
    # appt = Appointment.query.get(int(id))
    appt = findAppointmentById(appointments,int(id))
    if appt is None:
        return jsonify(error="not found"), 404
 
    appt.state = "no_show"
    # db.session.commit()                            
 
    return jsonify({
    "id": appt.id,
    "state": appt.state})

# 获取指定用户，日期的预约
def getAppointmentDay(stylist:User,date:date):
    start:datetime = datetime.combine(date, time.min) 
    end:datetime = start + timedelta(days=1) 
    appointments = select(Appointment).where(Appointment.stylist_id == stylist.id,start < Appointment.starts_at, Appointment.starts_at < end )
    return db.session.execute(appointments).scalars().all()

def findAppointmentById(appointments,id):
    for a in appointments:
        if a.id==id:
            return a
    return None
