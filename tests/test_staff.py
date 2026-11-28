"""
测试数据由AI生成，仅用于测试网页功能。

测试数据生成：仅在内存中构造 ORM 对象，不写入数据库。

数据覆盖：
- 顾客 2、发型师 2、管理员 2
- 预约 4 个（每位发型师各 2 个），时间均落在 date.today() 当天
- 配套的服务、工位、排班、不可用时段、关联表、时段占用

注意：这里只 new 出对象并相互引用，不调用 db.session.add / commit，
因此不会落库，可直接用于单测或调试。
"""

from datetime import date, datetime, time

from models import (
    Appointment,
    Service,
    SlotAllocation,
    StaffService,
    Unavailability,
    User,
    WorkingShift,
    Workstation,
)


def build_test_data():
    today = date.today()  # 2026-11-27

    # ---------------- 用户 ----------------
    # 顾客
    customer1 = User(id=1, name="王小明", email="wang@example.com",
                     role="customer", is_active=True)
    customer1.set_password("customer123")
    customer2 = User(id=2, name="赵小红", email="zhao@example.com",
                     role="customer", is_active=True)
    customer2.set_password("customer123")

    # 发型师
    stylist1 = User(id=3, name="张伟", email="zhangwei@salon.com",
                    role="stylist", is_active=True)
    stylist1.set_password("stylist123")
    stylist2 = User(id=4, name="李娜", email="lina@salon.com",
                    role="stylist", is_active=True)
    stylist2.set_password("stylist123")

    # 管理员
    admin1 = User(id=5, name="店长刘芳", email="boss@salon.com",
                  role="admin", is_active=True)
    admin1.set_password("admin123")
    admin2 = User(id=6, name="副店长陈强", email="deputy@salon.com",
                  role="admin", is_active=True)
    admin2.set_password("admin123")

    users = [customer1, customer2, stylist1, stylist2, admin1, admin2]

    # ---------------- 服务项目 ----------------
    svc_cut = Service(id=1, name="精剪造型", description="洗剪吹一体精剪服务",
                      price_minor=6800, duration_minutes=60,
                      required_workstation_type="chair", is_active=True)
    svc_color = Service(id=2, name="全头染发", description="进口染膏全头染色",
                        price_minor=26800, duration_minutes=120,
                        required_workstation_type="colour", is_active=True)
    svc_style = Service(id=3, name="日常造型", description="吹风盘发日常造型",
                        price_minor=3800, duration_minutes=45,
                        required_workstation_type="chair", is_active=True)
    services = [svc_cut, svc_color, svc_style]

    # ---------------- 发型师-服务关联 ----------------
    staff_services = [
        StaffService(stylist_id=stylist1.id, service_id=svc_cut.id),
        StaffService(stylist_id=stylist1.id, service_id=svc_color.id),
        StaffService(stylist_id=stylist2.id, service_id=svc_cut.id),
        StaffService(stylist_id=stylist2.id, service_id=svc_style.id),
    ]

    # ---------------- 工位 ----------------
    ws_chair1 = Workstation(id=1, label="1号剪发椅", workstation_type="chair",
                            is_active=True)
    ws_chair2 = Workstation(id=2, label="2号剪发椅", workstation_type="chair",
                            is_active=True)
    ws_colour1 = Workstation(id=3, label="1号染发位", workstation_type="colour",
                             is_active=True)
    workstations = [ws_chair1, ws_chair2, ws_colour1]

    # ---------------- 排班（今天） ----------------
    shifts = [
        WorkingShift(id=1, stylist_id=stylist1.id, work_date=today,
                     start_time=time(9, 0), end_time=time(18, 0)),
        WorkingShift(id=2, stylist_id=stylist2.id, work_date=today,
                     start_time=time(10, 0), end_time=time(19, 0)),
    ]

    # ---------------- 不可用时段（今天，避开下面预约） ----------------
    unavailabilities = [
        Unavailability(id=1, stylist_id=stylist1.id,
                       starts_at=datetime.combine(today, time(12, 0)),
                       ends_at=datetime.combine(today, time(13, 0)),
                       reason="break"),
        Unavailability(id=2, stylist_id=stylist2.id,
                       starts_at=datetime.combine(today, time(17, 0)),
                       ends_at=datetime.combine(today, time(18, 0)),
                       reason="leave"),
    ]

    # ---------------- 预约（每位发型师各 2 个，均在今天） ----------------
    # 发型师1：精剪 09:30-10:30（已完成）；染发 14:00-16:00（已确认）
    appt1 = Appointment(
        id=1, customer_id=customer1.id, stylist_id=stylist1.id,
        service_id=svc_cut.id, workstation_id=ws_chair1.id,
        starts_at=datetime.combine(today, time(9, 30)),
        ends_at=datetime.combine(today, time(10, 30)),
        agreed_price_minor=6800, status="completed",
        arrived_at=datetime.combine(today, time(9, 28)),
    )
    appt1.customer = customer1
    appt1.stylist = stylist1
    appt1.service = svc_cut
    appt1.workstation = ws_chair1

    appt2 = Appointment(
        id=2, customer_id=customer2.id, stylist_id=stylist1.id,
        service_id=svc_color.id, workstation_id=ws_colour1.id,
        starts_at=datetime.combine(today, time(14, 0)),
        ends_at=datetime.combine(today, time(16, 0)),
        agreed_price_minor=26800, status="confirmed",
        arrived_at=None,
    )
    appt2.customer = customer2
    appt2.stylist = stylist1
    appt2.service = svc_color
    appt2.workstation = ws_colour1

    # 发型师2：精剪 11:00-12:00（已确认）；造型 13:30-14:15（已取消）
    appt3 = Appointment(
        id=3, customer_id=customer1.id, stylist_id=stylist2.id,
        service_id=svc_cut.id, workstation_id=ws_chair2.id,
        starts_at=datetime.combine(today, time(11, 0)),
        ends_at=datetime.combine(today, time(12, 0)),
        agreed_price_minor=6800, status="confirmed",
        arrived_at=None,
    )
    appt3.customer = customer1
    appt3.stylist = stylist2
    appt3.service = svc_cut
    appt3.workstation = ws_chair2

    appt4 = Appointment(
        id=4, customer_id=customer2.id, stylist_id=stylist2.id,
        service_id=svc_style.id, workstation_id=ws_chair2.id,
        starts_at=datetime.combine(today, time(13, 30)),
        ends_at=datetime.combine(today, time(14, 15)),
        agreed_price_minor=3800, status="cancelled",
        arrived_at=None,
    )
    appt4.customer = customer2
    appt4.stylist = stylist2
    appt4.service = svc_style
    appt4.workstation = ws_chair2

    appointments = [appt1, appt2, appt3, appt4]

    # ---------------- 时段占用（与预约一一对应） ----------------
    slot_allocations = [
        SlotAllocation(id=1, appointment_id=appt1.id, stylist_id=stylist1.id,
                       workstation_id=ws_chair1.id,
                       slot_start=appt1.starts_at),
        SlotAllocation(id=2, appointment_id=appt2.id, stylist_id=stylist1.id,
                       workstation_id=ws_colour1.id,
                       slot_start=appt2.starts_at),
        SlotAllocation(id=3, appointment_id=appt3.id, stylist_id=stylist2.id,
                       workstation_id=ws_chair2.id,
                       slot_start=appt3.starts_at),
        SlotAllocation(id=4, appointment_id=appt4.id, stylist_id=stylist2.id,
                       workstation_id=ws_chair2.id,
                       slot_start=appt4.starts_at),
    ]

    # 建立预约 -> 时段占用 的一对多引用
    for appt in appointments:
        appt.slot_allocations = [
            sa for sa in slot_allocations if sa.appointment_id == appt.id
        ]

    return {
        "users": users,
        "services": services,
        "staff_services": staff_services,
        "workstations": workstations,
        "shifts": shifts,
        "unavailabilities": unavailabilities,
        "appointments": appointments,
        "slot_allocations": slot_allocations,
    }


# 模块导入即生成一份测试数据，可直接 from test_data import TEST_DATA 使用
TEST_DATA = build_test_data()


