from django.contrib import admin
from django.utils import timezone
from datetime import time, timedelta, datetime
from .models import (
    Staff, Dredger, DailyProjectReport, 
    WorkShift, PipeFighterOperations, InventoryItem, NewsTicker, AdminVault, WeeklyRotation
)
admin.site.site_header = "شركة قاصد خير للمقاولات"
admin.site.site_title = "بوابة إدارة المشاريع"
admin.site.index_title = "لوحة التحكم والعمليات"


# 1. عرض الورديات داخل التقرير المجمع (للمدير والمكتب الفني)
class WorkShiftInline(admin.StackedInline):
    model = WorkShift
    extra = 0
    # جعل الحقول للقراءة فقط داخل التقرير المجمع لضمان عدم التلاعب بالبيانات التاريخية
    readonly_fields = [
        'operator', 'shift_time', 'status', 'start_time', 'end_time', 
        'floating_line', 'land_line', 'start_east', 'start_north', 
        'end_east', 'end_north', 'quantity_m3', 'progress_meters', 
        'main_engine_hours', 'aux_engine_hours', 'fuel_usage'
    ]
    fieldsets = (
        ('معلومات الوردية', {'fields': (('operator', 'shift_time', 'status'), ('start_time', 'end_time'))}),
        ('بيانات الخط والإحداثيات', {'fields': (('floating_line', 'land_line'), ('start_east', 'start_north'), ('end_east', 'end_north'))}),
        ('الإنتاج والمحركات', {'fields': (('quantity_m3', 'progress_meters'), ('main_engine_hours', 'aux_engine_hours'), 'fuel_usage')}),
        ('الأعطال', {'fields': ('stop_reason', 'stop_image')}),
    )

@admin.register(WorkShift)
class WorkShiftAdmin(admin.ModelAdmin):
    list_display = ('operator', 'get_dredger', 'status', 'fuel_usage', 'main_engine_hours')
    
    # جعل الحقول الناتجة للقراءة فقط
    readonly_fields = ['fuel_usage', 'main_engine_hours', 'aux_engine_hours']

    def get_fields(self, request, obj=None):
        # 1. حالة "بدء تشغيل" (المشغل لسه بيستلم)
        if obj and obj.status == 'active' and not obj.end_time:
            return [
                'operator', 'status', 'start_time',
                'fuel_start', 'fuel_received',
                'main_engine_start', 'aux_engine_start',
                'start_east', 'start_north',
                'floating_line', 'land_line'
            ]

        # 2. حالة "تسجيل توقف" أو "تسليم وردية" (إظهار كل قراءات النهاية)
        if obj and (obj.status != 'active' or obj.end_time):
            fields = [
                'operator', 'status', 'start_time', 'end_time',
                'fuel_start', 'fuel_end',  # أظهرنا البداية عشان المشغل يفتكر
                'main_engine_start', 'main_engine_end',
                'aux_engine_start', 'aux_engine_end',
                'end_east', 'end_north',
                'progress_meters',
            ]
            
            if obj.status != 'active':
                fields += ['stop_reason', 'stop_image']
            else:
                fields += ['quantity_m3', 'progress_meters']
            
            return fields

        # القائمة الاحتياطية (للسوبر أدمن)
        return ['operator', 'status', 'start_time', 'end_time', 'fuel_start', 'fuel_end', 'main_engine_start', 'main_engine_end', 'aux_engine_start', 'aux_engine_end', 'quantity_m3', 'progress_meters', 'stop_reason']

    def get_dredger(self, obj):
        return obj.report_24h.dredger.name if obj.report_24h else "N/A"
    get_dredger.short_description = 'الكراكة'

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        dredger_id = request.GET.get('dredger_id')
        if dredger_id:
            prev = WorkShift.objects.filter(report_24h__dredger_id=dredger_id).order_by('-id').first()
            if prev:
                initial['fuel_start'] = prev.fuel_end
                initial['main_engine_start'] = prev.main_engine_end
                initial['aux_engine_start'] = prev.aux_engine_end
                initial['start_east'] = prev.end_east
                initial['start_north'] = prev.end_north
                initial['floating_line'] = prev.floating_line
                initial['land_line'] = prev.land_line
        return initial

    def has_add_permission(self, request):
        if request.user.is_superuser: return True
        current_rotation = WeeklyRotation.objects.order_by('-start_date').first()
        staff_member = Staff.objects.filter(user=request.user).first()
        if current_rotation and staff_member:
            return staff_member.group == current_rotation.active_group
        return False

    def has_change_permission(self, request, obj=None):
        # إذا كان سوبر أدمن، له كامل الصلاحية
        if request.user.is_superuser: return True
        
        # إذا كان السجل موجود (obj)، نتأكد أن المشغل هو صاحب السجل
        if obj is not None:
            return obj.operator.user == request.user
            
        # كخطة بديلة نستخدم نفس منطق الإضافة (دوران المجموعات A/B)
        return self.has_add_permission(request)


    def save_model(self, request, obj, form, change):
        if not obj.report_24h:
            now = timezone.now()
            report_date = now.date()
            if now.time() < time(12, 0): # تأكد من استيراد time
                report_date -= timedelta(days=1)
            dredger_id = request.GET.get('dredger_id')
            if dredger_id:
                try:
                    dredger_obj = Dredger.objects.get(id=dredger_id)
                    report, _ = DailyProjectReport.objects.get_or_create(dredger=dredger_obj, date_started=report_date)
                    obj.report_24h = report
                except: pass
        super().save_model(request, obj, form, change)

# 3. إعدادات التقرير اليومي المجمع
@admin.register(DailyProjectReport)
class DailyProjectReportAdmin(admin.ModelAdmin):
    list_display = ('dredger', 'date_started', 'is_closed')
    inlines = [WorkShiftInline]

    # حماية خانة "إغلاق التقرير" (للسوبر أدمن فقط)
    def get_readonly_fields(self, request, obj=None):
        if not request.user.is_superuser:
            return ['is_closed', 'dredger', 'date_started']
        return []

    def has_add_permission(self, request): return request.user.is_superuser
    def has_delete_permission(self, request, obj=None): return request.user.is_superuser

# 4. باقي الموديلات
@admin.register(WeeklyRotation)
class WeeklyRotationAdmin(admin.ModelAdmin):
    list_display = ('start_date', 'active_group')

@admin.register(AdminVault)
class AdminVaultAdmin(admin.ModelAdmin):
    list_display = ('staff_name', 'username', 'password_plain')
    def has_module_permission(self, request): return request.user.is_superuser

admin.site.register(Staff)
admin.site.register(Dredger)
admin.site.register(PipeFighterOperations)
admin.site.register(InventoryItem)
admin.site.register(NewsTicker)
