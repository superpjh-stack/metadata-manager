from django.urls import path
from django.contrib.auth import views as auth
from registry import views
urlpatterns = [
    path('healthz/',views.health,name='health'),
    path('accounts/login/',auth.LoginView.as_view(template_name='registration/login.html'),name='login'),
    path('accounts/logout/',auth.LogoutView.as_view(),name='logout'),
    path('',views.index,name='index'),
    path('overview/',views.overview,name='overview'),
    path('datasets/new/',views.edit,name='create'),
    path('datasets/<int:pk>/',views.detail,name='detail'),
    path('datasets/<int:pk>/edit/',views.edit,name='edit'),
    path('datasets/<int:pk>/checks/new/',views.check_edit,name='check_create'),
    path('datasets/<int:pk>/checks/<int:check_id>/',views.check_edit,name='check_edit'),
    path('datasets/<int:pk>/upload/',views.upload,name='upload'),
    path('attachments/<int:pk>/',views.attachment_download,name='attachment'),
    path('submissions/',views.submissions,name='submissions'),
    path('submissions/create/',views.submit_create,name='submit_create'),
    path('submissions/<uuid:pk>/download/',views.submission_download,name='submission_download'),
    path('import/',views.import_data,name='import'),
    path('import/template/',views.template_download,name='template'),
    path('settings/',views.settings_view,name='settings'),
    path('settings/accounts/',views.accounts,name='accounts'),
    path('settings/accounts/new/',views.account_create,name='account_create'),
    path('settings/fields/new/',views.extra_edit,name='extra_create'),
    path('settings/fields/<int:pk>/',views.extra_edit,name='extra_edit'),
]
