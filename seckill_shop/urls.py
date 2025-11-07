from django.contrib import admin
from django.urls import path

from shop import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.index, name='index'),
    path('buy/<int:product_id>/', views.buy, name='buy'),
    path('orders/', views.order_list, name='order_list'),
    path('order/pay/<int:order_id>/', views.pay_order, name='pay_order'),
    path('order/cancel/<int:order_id>/', views.cancel_order, name='cancel_order'),
    path('result/', views.pay_result, name='pay_result'),
    path('alipay/notify/', views.alipay_notify, name='alipay_notify'),

]
