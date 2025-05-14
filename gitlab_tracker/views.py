from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST
from datetime import datetime, timedelta
import traceback
import json

from .models import GitLabProfile
from .forms import CustomUserCreationForm, GitLabTokenForm
from .services import GitLabService

def home(request):
    """Home page view"""
    return render(request, 'home.html')

def register(request):
    """User registration view"""
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('dashboard')
    else:
        form = CustomUserCreationForm()
    
    return render(request, 'registration/register.html', {'form': form})

@login_required
def gitlab_setup(request):
    """GitLab token setup view"""
    try:
        profile = request.user.gitlab_profile
    except GitLabProfile.DoesNotExist:
        profile = GitLabProfile.objects.create(user=request.user)
    
    if request.method == 'POST':
        if 'delete' in request.POST:
            profile.delete()
            messages.success(request, 'GitLab profile deleted.')
            return redirect('gitlab_setup')
        form = GitLabTokenForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, 'GitLab token saved successfully!')
            return redirect('dashboard')
    else:
        form = GitLabTokenForm(instance=profile)
    
    return render(request, 'gitlab_setup.html', {'form': form, 'profile': profile, 'can_delete': profile.gitlab_token or profile.gitlab_host})

@login_required
def dashboard(request):
    """User dashboard view: only render the skeleton, no data fetching here!"""
    return render(request, 'dashboard.html', {})

@login_required
def tasks(request):
    """Daily tasks view: only render the skeleton, no data fetching here!"""
    # Get date from query string or use today
    date_str = request.GET.get('date')
    if date_str:
        try:
            selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            selected_date = timezone.now().date()
    else:
        selected_date = timezone.now().date()
    prev_date = selected_date - timedelta(days=1)
    next_date = selected_date + timedelta(days=1)
    today = timezone.now().date()
    if next_date > today:
        next_date = None
    context = {
        'selected_date': selected_date,
        'prev_date': prev_date,
        'next_date': next_date,
        'today': today,
    }
    return render(request, 'tasks.html', context)

# HTMX partial views
@login_required
def task_list_partial(request):
    """HTMX partial view for task list (live from GitLab)"""
    try:
        profile = request.user.gitlab_profile
        if not profile.has_token:
            return render(request, 'partials/task_list.html', {'error': "GitLab token not set"})
        date_str = request.GET.get('date')
        if date_str:
            try:
                selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                selected_date = timezone.now().date()
        else:
            selected_date = timezone.now().date()
        page = int(request.GET.get('page', 1))
        per_page = 100
        
        try:
            gitlab_service = GitLabService(profile.gitlab_token, getattr(profile, 'gitlab_host', None))
            date_for_api = selected_date.strftime('%Y-%m-%d')
            tasks, has_more = gitlab_service.get_daily_tasks(date_for_api, per_page=per_page, page=page)
            return render(request, 'partials/task_list.html', {'tasks': tasks, 'page': page, 'has_more': has_more, 'selected_date': selected_date})
        except Exception as inner_e:
            print(f"Error in GitLab API call: {str(inner_e)}")
            return render(request, 'partials/task_list.html', {'error': f"Error fetching tasks: {str(inner_e)}"})
    except Exception as e:
        print(f"Error in task_list_partial: {str(e)}")
        return render(request, 'partials/task_list.html', {'error': str(e)})

@login_required
def contribution_chart_partial(request):
    """HTMX partial view for contribution chart"""
    try:
        profile = request.user.gitlab_profile
        if not profile.has_token:
            return render(request, 'partials/contribution_chart.html', {'error': "GitLab token not set"})
        
        # Use GitLab service since MongoDB is not available
        gitlab_service = GitLabService(profile.gitlab_token, getattr(profile, 'gitlab_host', None))
        stats = gitlab_service.get_analytics(days=30)
        daily_contributions = stats.get('daily_contributions', [])
        
        return render(request, 'partials/contribution_chart.html', {
            'daily_contributions': daily_contributions
        })
    except Exception as e:
        return render(request, 'partials/contribution_chart.html', {'error': str(e)})

@login_required
def merge_requests_partial(request):
    """HTMX partial view for merge requests section"""
    try:
        profile = request.user.gitlab_profile
        if not profile.has_token:
            return render(request, 'partials/merge_requests.html', {'error': "GitLab token not set"})
        date_str = request.GET.get('date')
        if date_str:
            try:
                selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                selected_date = timezone.now().date()
        else:
            selected_date = timezone.now().date()
        
        try:
            gitlab_service = GitLabService(profile.gitlab_token, getattr(profile, 'gitlab_host', None))
            date_for_api = selected_date.strftime('%Y-%m-%d')
            grouped_tasks, _ = gitlab_service.get_daily_tasks(date_for_api, per_page=100, page=1)
            return render(request, 'partials/merge_requests.html', {
                'merge_requests': grouped_tasks.get('merge_requests', []),
                'pushes': grouped_tasks.get('pushes', [])
            })
        except Exception as inner_e:
            print(f"Error in GitLab API call for merge requests: {str(inner_e)}")
            return render(request, 'partials/merge_requests.html', {'error': f"Error fetching merge requests: {str(inner_e)}"})
    except Exception as e:
        print(f"Error in merge_requests_partial: {str(e)}")
        return render(request, 'partials/merge_requests.html', {'error': str(e)})

@login_required
def issues_partial(request):
    """HTMX partial view for issues section"""
    try:
        profile = request.user.gitlab_profile
        if not profile.has_token:
            return render(request, 'partials/issues.html', {'error': "GitLab token not set"})
        date_str = request.GET.get('date')
        if date_str:
            try:
                selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                selected_date = timezone.now().date()
        else:
            selected_date = timezone.now().date()
        
        try:
            gitlab_service = GitLabService(profile.gitlab_token, getattr(profile, 'gitlab_host', None))
            date_for_api = selected_date.strftime('%Y-%m-%d')
            grouped_tasks, _ = gitlab_service.get_daily_tasks(date_for_api, per_page=100, page=1)
            created_issues = []
            closed_issues = []
            for issue in grouped_tasks.get('issues', []):
                timestamp = issue.get('timestamp', '')
                if timestamp and timestamp.startswith(date_for_api):
                    if issue['action'] == 'opened':
                        created_issues.append(issue)
                    elif issue['action'] == 'closed':
                        closed_issues.append(issue)
            return render(request, 'partials/issues.html', {
                'created_issues': created_issues,
                'closed_issues': closed_issues
            })
        except Exception as inner_e:
            print(f"Error in GitLab API call for issues: {str(inner_e)}")
            return render(request, 'partials/issues.html', {'error': f"Error fetching issues: {str(inner_e)}"})
    except Exception as e:
        print(f"Error in issues_partial: {str(e)}")
        return render(request, 'partials/issues.html', {'error': str(e)})

@login_required
def pushes_partial(request):
    """HTMX partial view for pushes section - now this is just a placeholder since pushes are in merge_requests"""
    try:
        return HttpResponse("Pushes are now integrated with Merge Requests section")
    except Exception as e:
        return HttpResponse(f"Error: {str(e)}")

@login_required
def comments_partial(request):
    """HTMX partial view for comments section"""
    try:
        profile = request.user.gitlab_profile
        if not profile.has_token:
            return render(request, 'partials/comments.html', {'error': "GitLab token not set"})
        date_str = request.GET.get('date')
        if date_str:
            try:
                selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                selected_date = timezone.now().date()
        else:
            selected_date = timezone.now().date()
        
        try:
            gitlab_service = GitLabService(profile.gitlab_token, getattr(profile, 'gitlab_host', None))
            date_for_api = selected_date.strftime('%Y-%m-%d')
            grouped_tasks, _ = gitlab_service.get_daily_tasks(date_for_api, per_page=100, page=1)
            return render(request, 'partials/comments.html', {
                'comments': grouped_tasks.get('comments', [])
            })
        except Exception as inner_e:
            print(f"Error in GitLab API call for comments: {str(inner_e)}")
            return render(request, 'partials/comments.html', {'error': f"Error fetching comments: {str(inner_e)}"})
    except Exception as e:
        print(f"Error in comments_partial: {str(e)}")
        return render(request, 'partials/comments.html', {'error': str(e)})

@login_required
def other_partial(request):
    """HTMX partial view for other activity section"""
    try:
        profile = request.user.gitlab_profile
        if not profile.has_token:
            return render(request, 'partials/other.html', {'error': "GitLab token not set"})
        date_str = request.GET.get('date')
        if date_str:
            try:
                selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                selected_date = timezone.now().date()
        else:
            selected_date = timezone.now().date()
        
        try:
            gitlab_service = GitLabService(profile.gitlab_token, getattr(profile, 'gitlab_host', None))
            date_for_api = selected_date.strftime('%Y-%m-%d')
            grouped_tasks, _ = gitlab_service.get_daily_tasks(date_for_api, per_page=100, page=1)
            return render(request, 'partials/other.html', {
                'other': grouped_tasks.get('other', [])
            })
        except Exception as inner_e:
            print(f"Error in GitLab API call for other activities: {str(inner_e)}")
            return render(request, 'partials/other.html', {'error': f"Error fetching other activities: {str(inner_e)}"})
    except Exception as e:
        print(f"Error in other_partial: {str(e)}")
        return render(request, 'partials/other.html', {'error': str(e)})

@login_required
def dashboard_profile_header_partial(request):
    """HTMX partial view for dashboard profile header"""
    try:
        profile = request.user.gitlab_profile
        if not profile.has_token:
            return render(request, 'partials/dashboard/profile-header.html', {'error': "GitLab token not set"})
        gitlab_service = GitLabService(profile.gitlab_token, getattr(profile, 'gitlab_host', None))
        user_profile = gitlab_service.get_user_profile() or {}
        return render(request, 'partials/dashboard/profile-header.html', {'gitlab_user': user_profile})
    except Exception as e:
        return render(request, 'partials/dashboard/profile-header.html', {'gitlab_user': {}, 'error': str(e)})

@login_required
def dashboard_stats_partial(request):
    """HTMX partial view for dashboard statistics summary"""
    try:
        profile = request.user.gitlab_profile
        if not profile.has_token:
            return render(request, 'partials/dashboard/stats.html', {'error': "GitLab token not set"})
        gitlab_service = GitLabService(profile.gitlab_token, getattr(profile, 'gitlab_host', None))
        stats = gitlab_service.get_analytics(days=30) or {'total_contributions': 0, 'contribution_types': {}}
        
        # Calculate current streak
        daily_contributions = stats.get('daily_contributions', [])
        daily_contributions.sort(key=lambda x: x['date'], reverse=True)
        
        current_streak = 0
        today = timezone.now().date()
        
        # Convert dates to date objects for comparison
        for contribution in daily_contributions:
            contrib_date = datetime.strptime(contribution['date'], '%Y-%m-%d').date()
            days_diff = (today - contrib_date).days
            
            # If there's activity today or yesterday (to account for timezone differences)
            if days_diff == current_streak:
                current_streak += 1
            else:
                break
                
        return render(request, 'partials/dashboard/stats.html', {'stats': stats, 'current_streak': current_streak})
    except Exception as e:
        print(f"Error in dashboard_stats_partial: {str(e)}")
        return render(request, 'partials/dashboard/stats.html', {'stats': {'total_contributions': 0, 'contribution_types': {}}, 'error': str(e)})

@login_required
def dashboard_trend_chart_partial(request):
    """HTMX partial view for dashboard trend chart"""
    try:
        profile = request.user.gitlab_profile
        if not profile.has_token:
            return render(request, 'partials/dashboard/trend-chart.html', {'error': "GitLab token not set"})
        gitlab_service = GitLabService(profile.gitlab_token, getattr(profile, 'gitlab_host', None))
        stats = gitlab_service.get_analytics(days=30) or {'daily_contributions': []}
        labels = [d['date'] for d in stats.get('daily_contributions', [])]
        data = [d['count'] for d in stats.get('daily_contributions', [])]
        return render(request, 'partials/dashboard/trend-chart.html', {'labels': labels, 'data': data})
    except Exception as e:
        return render(request, 'partials/dashboard/trend-chart.html', {'labels': [], 'data': [], 'error': str(e)})

@login_required
def dashboard_activity_chart_partial(request):
    """HTMX partial view for dashboard activity breakdown chart"""
    try:
        profile = request.user.gitlab_profile
        if not profile.has_token:
            return render(request, 'partials/dashboard/activity-chart.html', {'error': "GitLab token not set"})
        gitlab_service = GitLabService(profile.gitlab_token, getattr(profile, 'gitlab_host', None))
        stats = gitlab_service.get_analytics(days=30) or {'contribution_types': {}}
        return render(request, 'partials/dashboard/activity-chart.html', {'stats': stats})
    except Exception as e:
        return render(request, 'partials/dashboard/activity-chart.html', {'stats': {'contribution_types': {}}, 'error': str(e)})

@login_required
def dashboard_types_summary_partial(request):
    """HTMX partial view for dashboard contribution types summary"""
    try:
        profile = request.user.gitlab_profile
        if not profile.has_token:
            return render(request, 'partials/dashboard/types-summary.html', {'error': "GitLab token not set"})
        gitlab_service = GitLabService(profile.gitlab_token, getattr(profile, 'gitlab_host', None))
        stats = gitlab_service.get_analytics(days=30) or {'total_contributions': 0, 'contribution_types': {}}
        return render(request, 'partials/dashboard/types-summary.html', {'stats': stats})
    except Exception as e:
        return render(request, 'partials/dashboard/types-summary.html', {'stats': {'total_contributions': 0, 'contribution_types': {}}, 'error': str(e)})

@login_required
def dashboard_recent_activity_partial(request):
    """HTMX partial view for dashboard recent activity"""
    try:
        profile = request.user.gitlab_profile
        if not profile.has_token:
            return render(request, 'partials/dashboard/recent-activity.html', {'error': "GitLab token not set"})
        gitlab_service = GitLabService(profile.gitlab_token, getattr(profile, 'gitlab_host', None))
        stats = gitlab_service.get_analytics(days=30) or {'contribution_types': {}}
        return render(request, 'partials/dashboard/recent-activity.html', {'stats': stats})
    except Exception as e:
        return render(request, 'partials/dashboard/recent-activity.html', {'stats': {'contribution_types': {}}, 'error': str(e)})

@login_required
def dashboard_contribution_heatmap_partial(request):
    """HTMX partial view for dashboard contribution heatmap"""
    try:
        profile = request.user.gitlab_profile
        if not profile.has_token:
            return render(request, 'partials/dashboard/contribution-heatmap.html', {'error': "GitLab token not set"})
        
        try:
            # Get GitLab analytics for last 60 days
            gitlab_service = GitLabService(profile.gitlab_token, getattr(profile, 'gitlab_host', None))
            stats = gitlab_service.get_analytics(days=60) or {'daily_contributions': []}
            
            # Convert daily contributions to a dict for easier lookup
            contributions_by_date = {}
            for item in stats.get('daily_contributions', []):
                contributions_by_date[item['date']] = item['count']
            
            # Generate calendar data for the contribution heatmap
            today = timezone.now().date()
            start_date = today - timedelta(days=42)  # Show about 6 weeks
            
            # Initialize calendar data structure
            calendar_data = []
            current_date = start_date
            
            # Group by week
            while current_date <= today:
                week_start = current_date - timedelta(days=current_date.weekday() + 1)  # Sunday is the start
                if week_start < start_date:
                    week_start = start_date
                
                # Create a week of data
                week_data = {
                    'date_display': week_start.day,
                    'month_display': week_start.strftime('%b'),
                    'show_date': week_start.day == 1 or len(calendar_data) == 0,  # Show month if it's the 1st or first week
                    'days': []
                }
                
                # Create days for this week
                for i in range(7):  # Sunday to Saturday
                    day_date = week_start + timedelta(days=i)
                    date_str = day_date.strftime('%Y-%m-%d')
                    
                    # Only include days within our range
                    in_range = start_date <= day_date <= today
                    
                    # Get count from contributions or default to 0
                    count = contributions_by_date.get(date_str, 0) if in_range else 0
                    
                    week_data['days'].append({
                        'date': date_str,
                        'count': count,
                        'in_range': in_range
                    })
                
                calendar_data.append(week_data)
                current_date = week_start + timedelta(days=7)
            
            return render(request, 'partials/dashboard/contribution-heatmap.html', {
                'calendar_data': calendar_data
            })
        except Exception as inner_e:
            print(f"Error generating contribution heatmap: {str(inner_e)}")
            return render(request, 'partials/dashboard/contribution-heatmap.html', {'error': f"Error generating heatmap: {str(inner_e)}"})
    except Exception as e:
        print(f"Error in dashboard_contribution_heatmap_partial: {str(e)}")
        return render(request, 'partials/dashboard/contribution-heatmap.html', {'error': str(e)})
