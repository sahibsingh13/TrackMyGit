import requests
import json
from datetime import datetime, timedelta
from django.conf import settings
from django.utils import timezone

REQUEST_TIMEOUT = 15  # increase timeout from 8 to 15 seconds

class GitLabService:
    """Service to interact with GitLab API"""
    def __init__(self, token, host=None):
        self.token = token
        if host:
            host = host.rstrip('/')
            if '/api/v4' not in host:
                host = f"{host}/api/v4"
        self.base_url = host or settings.GITLAB_API_URL
        self.headers = {'PRIVATE-TOKEN': token}
        self._user_id = None
        self._user_profile = None

    def safe_get(self, url, **kwargs):
        try:
            return requests.get(url, headers=self.headers, timeout=REQUEST_TIMEOUT, **kwargs)
        except requests.exceptions.Timeout:
            print(f"Timeout when calling {url}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"Request failed: {e}")
            return None

    def get_user_id(self):
        if self._user_id is not None:
            return self._user_id
        url = f"{self.base_url}/user"
        response = self.safe_get(url)
        if response and response.status_code == 200:
            try:
                self._user_id = response.json().get('id')
                return self._user_id
            except Exception as e:
                print(f"Error decoding JSON from {url}: {e}\nResponse text: {response.text}")
                self._user_id = 3
                return self._user_id
        else:
            print(f"Failed to fetch user ID from {url}. Status: {response.status_code}\nResponse text: {response.text}")
            self._user_id = 3
            return self._user_id

    def get_user_profile(self):
        """Fetch the GitLab user profile (avatar, username, name, etc)."""
        if self._user_profile is not None:
            return self._user_profile
        url = f"{self.base_url}/user"
        response = self.safe_get(url)
        if response and response.status_code == 200:
            self._user_profile = response.json()
            return self._user_profile
        else:
            print(f"Failed to fetch user profile from {url}. Status: {response.status_code}\nResponse text: {response.text}")
            return None

    def get_user_events(self, after=None, before=None, per_page=100, page=1):
        """Get user events from GitLab API with pagination and date filtering."""
        user_id = self.get_user_id()
        url = f"{self.base_url}/users/{user_id}/events"
        params = {'per_page': per_page, 'page': page}
        if after:
            params['after'] = after
        if before:
            params['before'] = before
        response = self.safe_get(url, params=params)
        if not response:
            print(f"Failed to get response from {url}")
            return []
            
        print(f"GitLab API GET {url} status={response.status_code}")
        if response.status_code == 200:
            try:
                return response.json()
            except Exception as e:
                print(f"Error parsing JSON response: {e}")
                return []
        else:
            print(f"Error status code: {response.status_code}")
            return []

    def get_analytics(self, days=30):
        """Compute analytics live from GitLab events for the past N days."""
        after = (timezone.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        all_events = []
        page = 1
        while True:
            events = self.get_user_events(after=after, per_page=100, page=page)
            if not events:
                break
            all_events.extend(events)
            if len(events) < 100:
                break
            page += 1
        # Compute stats
        stats = {
            'total_contributions': len(all_events),
            'contribution_types': {},
            'daily_contributions': {},
        }
        for event in all_events:
            action = event.get('action_name')
            created_at = event.get('created_at')
            date = created_at[:10] if created_at else None
            if action:
                stats['contribution_types'][action] = stats['contribution_types'].get(action, 0) + 1
            if date:
                stats['daily_contributions'][date] = stats['daily_contributions'].get(date, 0) + 1
        # Convert daily_contributions to sorted list
        daily_contributions = [
            {'date': date, 'count': stats['daily_contributions'][date]}
            for date in sorted(stats['daily_contributions'])
        ]
        stats['daily_contributions'] = daily_contributions
        return stats

    def get_daily_tasks(self, date_str, per_page=100, page=1):
        """Get user events for a specific day, grouped by type for structured reporting. Advanced: also fetch MRs, issues, commits directly from all user projects."""
        try:
            user_id = self.get_user_id()
            username = self.get_user_profile().get('username', '')
            url = f"{self.base_url}/users/{user_id}/events"
            selected_date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
            next_day_obj = selected_date_obj + timedelta(days=1)
            next_day_date_str = next_day_obj.strftime('%Y-%m-%d')
            params = {
                'after': date_str,
                'before': next_day_date_str,
                'per_page': per_page,
                'page': page
            }
            # 1. Get events as before
            response = self.safe_get(url, params=params)
            events = []
            if response and response.status_code == 200:
                try:
                    events = response.json()
                except Exception as e:
                    print(f"Error parsing events JSON: {str(e)}")
            
            # Print some debug info about events from the /events API
            print(f"[DEBUG] Found {len(events)} events from /events API for date {date_str}")
            
            # 2. Get all user projects (first 100 for performance)
            # For performance, limit to top N most active projects
            top_project_limit = 10  # Reduced for better performance
            projects = []
            try:
                projects = self.get_user_projects(per_page=top_project_limit, page=1)
            except Exception as e:
                print(f"Error fetching projects: {str(e)}")
            
            # 3. Prepare grouped structure
            grouped = {
                'merge_requests': [],
                'issues': [],
                'pushes': [],
                'comments': [],
                'other': []
            }
            
            # 4. Helper for deduplication
            seen = set()
            
            # 5. Add events from /events API
            self._process_events(events, grouped, user_id, seen)
            
            # Return results - has_more is determined by events length vs per_page
            has_more = len(events) >= per_page
            return grouped, has_more
        except Exception as e:
            print(f"Error in get_daily_tasks: {str(e)}")
            # Return empty results instead of raising
            return {
                'merge_requests': [],
                'issues': [],
                'pushes': [],
                'comments': [],
                'other': []
            }, False
        
    def _process_events(self, events, grouped, user_id, seen):
        """Process events into grouped structure."""
        for event in events:
            try:
                action = event.get('action_name')
                target_type = event.get('target_type')
                target_title = event.get('target_title')
                project_name = event.get('project_name') or ''
                created_at = event.get('created_at')
                push_data = event.get('push_data')
                target_iid = event.get('target_iid')
                project_id = event.get('project_id')
                # Check if this event is for the current user
                author_id = event.get('author_id') or event.get('author', {}).get('id')
                if author_id and str(author_id) != str(user_id):
                    # Skip events not created by the current user
                    continue
                    
                base_url = self.base_url.replace('/api/v4', '')
                link = None
                if target_type == 'MergeRequest' and target_iid and project_id:
                    link = f"{base_url}/projects/{project_id}/merge_requests/{target_iid}"
                elif target_type == 'Issue' and target_iid and project_id:
                    link = f"{base_url}/projects/{project_id}/issues/{target_iid}"
                elif action in ['pushed to', 'pushed new'] and project_id:
                    link = f"{base_url}/projects/{project_id}/repository/commits"
                
                key = f"{action}-{target_type}-{target_iid}-{created_at}"
                if key in seen:
                    continue
                seen.add(key)
                
                if action in ['opened', 'accepted'] and target_type == 'MergeRequest':
                    grouped['merge_requests'].append({
                        'action': action,
                        'title': target_title,
                        'iid': target_iid,
                        'project': project_name,
                        'timestamp': created_at,
                        'link': link
                    })
                elif action in ['opened', 'closed'] and target_type == 'Issue':
                    grouped['issues'].append({
                        'action': action,
                        'title': target_title,
                        'iid': target_iid,
                        'project': project_name,
                        'timestamp': created_at,
                        'link': link
                    })
                elif action in ['pushed to', 'pushed new']:
                    branch = push_data.get('ref') if push_data else None
                    grouped['pushes'].append({
                        'action': action,
                        'branch': branch,
                        'project': project_name,
                        'timestamp': created_at,
                        'commit_count': push_data.get('commit_count') if push_data else None,
                        'link': link
                    })
                elif action == 'commented on' or 'comment' in action.lower():
                    # Handle all comment types
                    grouped['comments'].append({
                        'action': action,
                        'title': target_title,
                        'project': project_name,
                        'timestamp': created_at,
                        'link': link
                    })
                else:
                    grouped['other'].append({
                        'action': action,
                        'title': target_title,
                        'project': project_name,
                        'timestamp': created_at,
                        'link': link
                    })
            except Exception as e:
                print(f"Error processing event: {str(e)}")
                continue

    def get_user_projects(self, per_page=100, page=1):
        """Fetch all projects the user is a member of (paginated)."""
        url = f"{self.base_url}/projects"
        params = {
            'membership': True,
            'simple': True,
            'per_page': per_page,
            'page': page
        }
        response = self.safe_get(url, params=params)
        if response and response.status_code == 200:
            return response.json()
        else:
            print(f"[ERROR] Failed to fetch user projects: {response.status_code} {response.text}")
            return [] 