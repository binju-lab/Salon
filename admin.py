from flask import Blueprint, abort, redirect, render_template, request, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from wtforms import HiddenField, IntegerField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, NumberRange
from models import Service
from tests.test_staff import TEST_DATA

# Role D: Ruizhe Zheng 24107708
# 管理页面后端代码
admin = Blueprint("admin", __name__, url_prefix='/admin')
db = SQLAlchemy()

# 暂时使用测试数据，后续与数据库连接
def getCurrentAdmin():
    return TEST_DATA["users"][4]
def getServices():
    return TEST_DATA["services"]
def getStaffServices():
    return TEST_DATA["staff_services"]
def getWorkstations():
    return TEST_DATA["workstations"]
def getShifts():
    return TEST_DATA["shifts"]
def getUnavailabilities():
    return TEST_DATA["unavailabilities"]
def getOverview():
    return TEST_DATA["appointments"]

user = getCurrentAdmin()
servicelist = getServices()



# 登录到管理页面，主页 http://127.0.0.1:5000/admin/services

#上方nav导航栏跳转6个页面：
@admin.get('/services')
def services():
    return render_template('admin/adminServices.html',user=user,services=servicelist)
@admin.get('/staff-services')
def staff_services():
    return render_template('admin/adminStaffServices.html',user=user,staff_services=getStaffServices())
@admin.get('/workstations')
def workstations():
    return render_template('admin/adminWorkstations.html',user=user,workstations=getWorkstations())
@admin.get('/shifts')
def shifts():
    return render_template('admin/adminShifts.html',user=user,working_shifts=getShifts())
@admin.get('/unavailability')
def unavailability():
    return render_template('admin/adminUnavailability.html',user=user,unavailabilities=getUnavailabilities())
@admin.get('/overview')
def overview():
    return render_template('admin/adminOverview.html',user=user,appointments=getOverview())


@admin.get('/services/new')
def addService():
    newid = len(servicelist)+1
    form = ServiceForm(obj=None)
    form.id.data = newid
    return render_template('admin/editService.html',user=user,form=form,op="add")

@admin.get('/services/<id>/edit')
def editService(id):
    service = findServiceById(servicelist,int(id))
    form = ServiceForm(obj=service)
    form.id.data = id
    return render_template('admin/editService.html',user=user,form=form,op="edit")

@admin.post('/services/<id>/<op>')
def submitService(id,op):
    print("service operation: "+op)
    form = ServiceForm()
    if form.validate_on_submit():
        data = {
            'id': form.id.data,
            'name': form.name.data,
            'description': form.description.data,
            'price_minor': form.price_minor.data,
            'duration_minutes': form.duration_minutes.data,
            'workstation_type': form.required_workstation_type.data,
            'is_active': True
        }
        match op:
            case "add":
                servicelist.append(data)
                return redirect(url_for('admin.services'))
            case "edit":
                ser = findServiceById(servicelist,int(id))
                ser.name = data['name']
                ser.description = data['description']
                ser.price_minor = data['price_minor']
                ser.duration_minutes = data['duration_minutes']
                ser.required_workstation_type = data['workstation_type']
                ser.is_active = data['is_active']
                return redirect(url_for('admin.services'))
            case _:
                abort(400, description=f"Unknown operation: {op}")
    else:
        return render_template('admin/editService.html',user=user,form=form,op=op)

    

class ServiceForm(FlaskForm):
    id = HiddenField()
    name = StringField('name', validators=[DataRequired()])
    description = StringField('description', validators=[DataRequired()])

    price_minor = IntegerField(
        'price_minor',
        validators=[DataRequired(), NumberRange(min=0)]
    )
    duration_minutes = IntegerField(
        'duration(minutes)',
        validators=[DataRequired(), NumberRange(min=15, max=120)]
    )
    required_workstation_type = SelectField(
        'workstation_type',
        choices=[('', ''), ('chair', 'chair'), ('colour', 'colour')],
        validators=[DataRequired()],
    )
    submit = SubmitField('submit', render_kw={'class': 'btn btn-primary'})

def findServiceById(services,id):
    for s in services:
        if s.id == id:
            return s
    return None



