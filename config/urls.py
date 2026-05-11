"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from core import views
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views

urlpatterns = [
    # 1. لوحة الأدمين (تم إرجاعها للمكان الصحيح)
    path('admin/', admin.site.urls),
    
    # 2. نظام الدخول
    path('accounts/login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),

    # 3. الصفحة الرئيسية
    path('', views.home, name='home'),

    # --- قسم التقارير العامة ---
    path('analytics/', views.analytics, name='analytics'), 
    path('reports/', views.reports_list, name='reports_list'),
    path('reports/<int:report_id>/', views.report_detail, name='report_detail'),
    path('fuel-monitor/', views.fuel_report, name='fuel_report'),

    # --- قسم البايب فيتر (الخط) ---
    path('pipe-report/new/', views.pipefighter_form_view, name='pipe_report'),
    path('pipe-report/<int:report_id>/', views.pipe_report_detail, name='pipe_report_detail'),

    # --- قسم جرد بحرية الكراكة (المشغلين) ---
    path('marine-inventory/new/', views.start_marine_inventory, name='start_marine_inventory'),
    path('marine-inventory/list/', views.marine_inventory_list, name='marine_inventory_list'),
    path('marine-inventory/print/<int:report_id>/', views.print_marine_inventory, name='print_marine_inventory'),

    # --- قسم مخزن البر / الموقع (الإنفنتوري) ---
    # صفحة العرض (Hub)
    path('site-inventory/', views.site_inventory_view, name='site_inventory_view'),
    
    # صفحة تسجيل جرد البر (الفصل التام عن البحرية)
    path('inventory/site-entry/', views.site_inventory_entry, name='land_inventory'),
    
    # صفحة الطباعة الرسمية للمخزن
    path('inventory/print-official/', views.inventory_print, name='inventory_print_official'),

    # الأكشن السريع (بدء/توقف)
    path('action/<int:dredger_id>/<str:action_type>/', views.quick_action, name='quick_action'),
] 

# إعدادات الأخطاء والصور (مرة واحدة فقط لمنع التكرار)
handler403 = 'core.views.error_403'
handler404 = 'core.views.error_404'

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
