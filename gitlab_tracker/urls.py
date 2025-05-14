from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from .forms import CustomLoginForm

urlpatterns = [
    # Main pages
    path('', views.home, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('tasks/', views.tasks, name='tasks'),
    
    # Authentication
    path('login/', auth_views.LoginView.as_view(
        template_name='registration/login.html',
        authentication_form=CustomLoginForm
    ), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('register/', views.register, name='register'),
    
    # GitLab setup
    path('gitlab-setup/', views.gitlab_setup, name='gitlab_setup'),
    
    # HTMX partials
    path('partials/task-list/', views.task_list_partial, name='task_list_partial'),
    path('partials/contribution-chart/', views.contribution_chart_partial, name='contribution_chart_partial'),
    path('partials/merge-requests/', views.merge_requests_partial, name='merge_requests_partial'),
    path('partials/issues/', views.issues_partial, name='issues_partial'),
    path('partials/pushes/', views.pushes_partial, name='pushes_partial'),
    path('partials/comments/', views.comments_partial, name='comments_partial'),
    path('partials/other/', views.other_partial, name='other_partial'),

    # Dashboard HTMX partials
    path('partials/dashboard/profile-header/', views.dashboard_profile_header_partial, name='dashboard_profile_header_partial'),
    path('partials/dashboard/stats/', views.dashboard_stats_partial, name='dashboard_stats_partial'),
    path('partials/dashboard/trend-chart/', views.dashboard_trend_chart_partial, name='dashboard_trend_chart_partial'),
    path('partials/dashboard/activity-chart/', views.dashboard_activity_chart_partial, name='dashboard_activity_chart_partial'),
    path('partials/dashboard/types-summary/', views.dashboard_types_summary_partial, name='dashboard_types_summary_partial'),
    path('partials/dashboard/recent-activity/', views.dashboard_recent_activity_partial, name='dashboard_recent_activity_partial'),
] 