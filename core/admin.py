from django.contrib import admin
from django.utils.safestring import mark_safe
from django.utils import timezone
from datetime import time, timedelta
from .models import (
    PipeFighterExtraItem, WorkShift, Staff, Dredger, DailyProjectReport, 
    WeeklyRotation, PipeFighterOperations, NewsTicker, AdminVault, InventoryItem,
    SupportEquipment, FuelMovement, MarineInventoryDetail, MarineInventoryReport
)

# إعدادات واجهة الأدمين
admin.site.site_header = "شركة قاصد خير للمقاولات"
admin.site.site_title = "بوابة إدارة المشاريع"
admin.site.index_title = "لوحة التحكم والعمليات"

def is_super(request):
    return request.user.is_active and request.user.is_superuser

# دالة الحماية لمنع تعارض الـ AlreadyRegistered وتصفير الذاكرة
def safe_register(model, admin_class=None):
    try:
        if admin.site.is_registered(model):
            admin.site.unregister(model)
        if admin_class:
            admin.site.register(model, admin_class)
        else:
            admin.site.register(model)
    except Exception:
        pass

# ==========================================
# 1. إدارة ورديات الكراكة (أزرار الكراكة)
# ==========================================
class WorkShiftAdmin(admin.ModelAdmin):
    list_display = ('operator', 'get_dredger', 'status', 'fuel_usage', 'main_engine_hours')
    readonly_fields = ['fuel_usage', 'main_engine_hours', 'aux_engine_hours', 'quantity_m3']

    def has_module_permission(self, request): return True
    def has_view_permission(self, request, obj=None): return True

    def has_add_permission(self, request):
        if is_super(request): return True
        curr = WeeklyRotation.objects.order_by('-start_date').first()
        staff = Staff.objects.filter(user=request.user).first()
        return bool(curr and staff and staff.group == curr.active_group)

    def has_change_permission(self, request, obj=None):
        if is_super(request): return True
        if obj: return obj.operator.user == request.user
        return self.has_add_permission(request)

    def get_fields(self, request, obj=None):
        base = ['operator', 'status', 'start_time', 'end_time']
        engines = ['main_engine_start', 'main_engine_end', 'aux_engine_start', 'aux_engine_end']
        location = ['start_east', 'start_north', 'end_east', 'end_north']
        lines = ['floating_line', 'land_line']
        optional = ['fuel_start', 'fuel_received', 'fuel_end', 'progress_meters', 
                    'depth_before', 'depth_after', 'swing_width', 'quantity_m3', 
                    'stop_reason', 'stop_image']
        return base + engines + location + lines + optional

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        is_add = obj is None
        
        js_code = mark_safe(f"""
            <style>
                .kased-btn-group {{ width: 100%; text-align: center; padding: 15px; background: #f8f9fa; margin: 10px 0; border-radius: 8px; border: 1px solid #ddd; }}
                .kased-btn {{ background: #1a2a3a; color: #d4af37; border: 2px solid #d4af37; padding: 8px 25px; border-radius: 5px; cursor: pointer; font-weight: bold; margin: 5px; }}
                .hidden-row {{ display: none !important; }}
                .readonly-highlight {{ color: #d4af37 !important; font-weight: 900 !important; font-size: 1.3em !important; }}
            </style>
            <script>
            (function(){{
                var setup = function(){{
                    var target = document.querySelector('#workshift_form');
                    if(target && !document.querySelector('#kased_btns')){{
                        var f_fuel = document.querySelectorAll('.field-fuel_start, .field-fuel_received, .field-fuel_end');
                        var f_prog = document.querySelectorAll('.field-progress_meters, .field-depth_before, .field-depth_after, .field-swing_width, .field-quantity_m3');
                        var f_stop = document.querySelectorAll('.field-stop_reason, .field-stop_image');
                        [...f_fuel, ...f_prog, ...f_stop].forEach(el => {{ if(el) el.classList.add('hidden-row'); }});
                        var div = document.createElement('div'); div.id = 'kased_btns'; div.className = 'kased-btn-group';
                        var createBtn = (txt, rows) => {{
                            var b = document.createElement('button'); b.type = 'button'; b.className = 'kased-btn'; b.innerText = txt;
                            b.onclick = function() {{ rows.forEach(r => {{ if(r) r.classList.toggle('hidden-row'); }}); }}; return b;
                        }};
                        div.appendChild(createBtn('⛽ تسجيل السولار', f_fuel));
                        div.appendChild(createBtn('📏 تسجيل التقدم والأعماق', f_prog));
                        div.appendChild(createBtn('⚠️ وصف التوقف', f_stop));
                        target.prepend(div);
                        var calc = function() {{
                            var d1 = parseFloat(document.querySelector('#id_depth_before')?.value) || 0;
                            var d2 = parseFloat(document.querySelector('#id_depth_after')?.value) || 0;
                            var p = parseFloat(document.querySelector('#id_progress_meters')?.value) || 0;
                            var s = parseFloat(document.querySelector('#id_swing_width')?.value) || 0;
                            var res = (Math.abs(d2 - d1) * p * s).toFixed(2);
                            var out = document.querySelector('.field-quantity_m3 .readonly');
                            if(out) {{ out.innerText = res + ' متر مكعب'; out.classList.add('readonly-highlight'); }}
                        }};
                        ['#id_depth_before', '#id_depth_after', '#id_progress_meters', '#id_swing_width'].forEach(id => {{
                            document.querySelector(id)?.addEventListener('input', calc);
                        }});
                    }}
                }};
                setTimeout(setup, 600);
            }})();
            </script>
        """)
        if 'operator' in form.base_fields: form.base_fields['operator'].help_text = js_code
        return form

    def get_dredger(self, obj): return obj.report_24h.dredger.name if obj.report_24h else "N/A"
    get_dredger.short_description = 'الكراكة'

# ==========================================
# 2. إدارة عمليات الـ Pipe Fighter (الـ 8 أزرار)
# ==========================================
class ExtraItemInline(admin.TabularInline):
    model = PipeFighterExtraItem
    extra = 1

class PipeFighterAdmin(admin.ModelAdmin):
    list_display = ('date', 'shift', 'operator_in_charge', 'total_line_length')
    readonly_fields = ['float_length', 'land_length', 'total_line_length']
    inlines = [ExtraItemInline]

    def has_module_permission(self, request): return True
    def has_view_permission(self, request, obj=None): return True
    def has_add_permission(self, request): return request.user.is_superuser or Staff.objects.filter(user=request.user).exists()
    def has_change_permission(self, request, obj=None):
        if request.user.is_superuser: return True
        if obj and obj.operator_in_charge: return obj.operator_in_charge.user == request.user
        return self.has_add_permission(request)

# ==========================================
# 3. إدارة المخازن والجرد (النظام المطور والمختصر للفلتر الجانبي)
# ==========================================
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'category', 
        'show_in_site', 'show_in_marine', 'show_in_pipe', 
        'quantity_site', 'quantity_marine', 'quantity_pipe'
    )
    # تنظيف الفلتر تماماً: شلنا الـ 3 مربعات المسببة للزحمة واكتفينا بالقسم عشان يرجع الجدول مفرود واسع
    list_filter = ('category',) 
    search_fields = ('name',)

class MarineInventoryReportAdmin(admin.ModelAdmin):
    list_display = ('id', 'date', 'operator', 'report_type')
    list_filter = ('report_type', 'date')

class StaffAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'group', 'role')

# ==========================================
# 4. التسجيل الفولاذي الشامل لكل الموديلات القديمة والجديدة لمنع التكرار
# ==========================================
safe_register(WorkShift, WorkShiftAdmin)
safe_register(PipeFighterOperations, PipeFighterAdmin)
safe_register(InventoryItem, InventoryItemAdmin)
safe_register(MarineInventoryReport, MarineInventoryReportAdmin)
safe_register(Staff, StaffAdmin)

# إرجاع كافة الموديلات المفقودة للوحة الإدارة فوراً
safe_register(Dredger)
safe_register(DailyProjectReport)
safe_register(WeeklyRotation)
safe_register(NewsTicker)
safe_register(AdminVault)
safe_register(MarineInventoryDetail)
safe_register(SupportEquipment)
safe_register(FuelMovement)
safe_register(PipeFighterExtraItem)
