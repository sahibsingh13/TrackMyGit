import requests
import json
from datetime import datetime, timedelta
from django.conf import settings
from django.utils import timezone

REQUEST_TIMEOUT = 8  # seconds

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
        print(f"GitLab API GET {url} status={response.status_code}\nResponse text: {response.text[:500]}")
        if response and response.status_code == 200:
            return response.json()
        else:
            response.raise_for_status()

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
        events = response.json() if response and response.status_code == 200 else []
        
        # Print some debug info about events from the /events API
        print(f"[DEBUG] Found {len(events)} events from /events API for date {date_str}")
        
        # 2. Get all user projects (first 100 for performance)
        # For performance, limit to top N most active projects
        top_project_limit = 20
        projects = self.get_user_projects(per_page=top_project_limit, page=1)
        
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
        for event in events:
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
        
        # Process projects in parallel for better performance
        if not grouped['pushes'] or not grouped['comments']:
            # Only process if we need to find more pushes or comments
            for project in projects:
                project_id = project['id']
                project_name = project['name_with_namespace']
                base_url = self.base_url.replace('/api/v4', '')
                
                # Find all comments from discussion notes (much more reliable)
                if not grouped['comments']:
                    self._fetch_comments(project_id, project_name, base_url, date_str, next_day_date_str, user_id, seen, grouped)
                
                # Find pushes using multiple methods
                if not grouped['pushes']:
                    self._fetch_pushes_and_commits(project_id, project_name, base_url, date_str, next_day_date_str, user_id, username, seen, grouped)
                
                # Find merge requests
                self._fetch_merge_requests(project_id, project_name, base_url, date_str, next_day_date_str, username, seen, grouped)
                
                # Find issues
                self._fetch_issues(project_id, project_name, base_url, date_str, next_day_date_str, username, seen, grouped)
        
        # Debug output
        print(f"[DEBUG] Found {len(grouped['merge_requests'])} merge requests")
        print(f"[DEBUG] Found {len(grouped['issues'])} issues")
        print(f"[DEBUG] Found {len(grouped['pushes'])} pushes")
        print(f"[DEBUG] Found {len(grouped['comments'])} comments")
        print(f"[DEBUG] Found {len(grouped['other'])} other activities")
        
        return grouped, len(events) == per_page  # Return grouped tasks and if there might be more
    
    def _fetch_comments(self, project_id, project_name, base_url, date_str, next_day_date_str, user_id, seen, grouped):
        """Fetch all comments/notes for a project"""
        try:
            # Get all MRs for this project (to look for comments)
            mr_url = f"{self.base_url}/projects/{project_id}/merge_requests"
            mr_params = {
                'updated_after': date_str + 'T00:00:00Z',
                'updated_before': next_day_date_str + 'T00:00:00Z',
                'per_page': 50
            }
            
            mr_resp = self.safe_get(mr_url, params=mr_params)
            if mr_resp and mr_resp.status_code == 200:
                # For each MR, get their notes
                for mr in mr_resp.json():
                    mr_iid = mr.get('iid')
                    mr_title = mr.get('title', '')
                    
                    # Get notes for this MR
                    mr_notes_url = f"{self.base_url}/projects/{project_id}/merge_requests/{mr_iid}/notes"
                    notes_params = {
                        'created_after': date_str + 'T00:00:00Z',
                        'created_before': next_day_date_str + 'T00:00:00Z',
                        'per_page': 50
                    }
                    
                    notes_resp = self.safe_get(mr_notes_url, params=notes_params)
                    if notes_resp and notes_resp.status_code == 200:
                        for note in notes_resp.json():
                            # Check if the note is by the current user
                            if note.get('author', {}).get('id') != user_id:
                                continue
                                
                            created_at = note.get('created_at')
                            if not created_at or not created_at.startswith(date_str):
                                continue
                                
                            key = f"comment-mr-{mr_iid}-{note.get('id')}-{created_at}"
                            if key in seen:
                                continue
                            seen.add(key)
                            
                            grouped['comments'].append({
                                'action': 'commented on MR',
                                'title': mr_title,
                                'project': project_name,
                                'timestamp': created_at,
                                'link': mr.get('web_url') or f"{base_url}/projects/{project_id}/merge_requests/{mr_iid}"
                            })
            
            # Get all issues for this project (to look for comments)
            issue_url = f"{self.base_url}/projects/{project_id}/issues"
            issue_params = {
                'updated_after': date_str + 'T00:00:00Z',
                'updated_before': next_day_date_str + 'T00:00:00Z',
                'per_page': 50
            }
            
            issue_resp = self.safe_get(issue_url, params=issue_params)
            if issue_resp and issue_resp.status_code == 200:
                # For each issue, get their notes
                for issue in issue_resp.json():
                    issue_iid = issue.get('iid')
                    issue_title = issue.get('title', '')
                    
                    # Get notes for this issue
                    issue_notes_url = f"{self.base_url}/projects/{project_id}/issues/{issue_iid}/notes"
                    notes_params = {
                        'created_after': date_str + 'T00:00:00Z',
                        'created_before': next_day_date_str + 'T00:00:00Z',
                        'per_page': 50
                    }
                    
                    notes_resp = self.safe_get(issue_notes_url, params=notes_params)
                    if notes_resp and notes_resp.status_code == 200:
                        for note in notes_resp.json():
                            # Check if the note is by the current user
                            if note.get('author', {}).get('id') != user_id:
                                continue
                                
                            created_at = note.get('created_at')
                            if not created_at or not created_at.startswith(date_str):
                                continue
                                
                            key = f"comment-issue-{issue_iid}-{note.get('id')}-{created_at}"
                            if key in seen:
                                continue
                            seen.add(key)
                            
                            grouped['comments'].append({
                                'action': 'commented on issue',
                                'title': issue_title,
                                'project': project_name,
                                'timestamp': created_at,
                                'link': issue.get('web_url') or f"{base_url}/projects/{project_id}/issues/{issue_iid}"
                            })
                            
            # Try to get commit comments
            commit_url = f"{self.base_url}/projects/{project_id}/repository/commits"
            commit_params = {
                'since': date_str + 'T00:00:00Z',
                'until': next_day_date_str + 'T00:00:00Z',
                'per_page': 50
            }
            
            commit_resp = self.safe_get(commit_url, params=commit_params)
            if commit_resp and commit_resp.status_code == 200:
                for commit in commit_resp.json():
                    commit_id = commit.get('id')
                    
                    # Get notes for this commit
                    commit_notes_url = f"{self.base_url}/projects/{project_id}/repository/commits/{commit_id}/comments"
                    notes_resp = self.safe_get(commit_notes_url)
                    
                    if notes_resp and notes_resp.status_code == 200:
                        for note in notes_resp.json():
                            # Check if the note is by the current user
                            if note.get('author', {}).get('id') != user_id:
                                continue
                                
                            created_at = note.get('created_at') or note.get('committed_date')
                            if not created_at or not created_at.startswith(date_str):
                                continue
                                
                            key = f"comment-commit-{commit_id}-{note.get('id', note.get('note_id'))}-{created_at}"
                            if key in seen:
                                continue
                            seen.add(key)
                            
                            commit_msg = commit.get('title', commit.get('message', '')[:50])
                            grouped['comments'].append({
                                'action': 'commented on commit',
                                'title': commit_msg,
                                'project': project_name,
                                'timestamp': created_at,
                                'link': f"{base_url}/projects/{project_id}/commit/{commit_id}"
                            })
                            
        except Exception as e:
            print(f"[WARNING] Error fetching comments: {str(e)}")
    
    def _fetch_pushes_and_commits(self, project_id, project_name, base_url, date_str, next_day_date_str, user_id, username, seen, grouped):
        """Fetch all pushes and commits for a project"""
        try:
            # 1. Try repository/commits first
            commit_url = f"{self.base_url}/projects/{project_id}/repository/commits"
            commit_params = {
                'all': 'true',  # Look at all commits then filter by author
                'since': date_str + 'T00:00:00Z',
                'until': next_day_date_str + 'T00:00:00Z',
                'per_page': 50
            }
            
            commit_resp = self.safe_get(commit_url, params=commit_params)
            if commit_resp and commit_resp.status_code == 200:
                commits = commit_resp.json()
                # Get commit authors/committers
                for commit in commits:
                    author_email = commit.get('author_email', '').lower()
                    author_name = commit.get('author_name', '').lower()
                    committer_name = commit.get('committer_name', '').lower()
                    
                    # Match with real name, username or email
                    user_profile = self.get_user_profile() or {}
                    user_email = user_profile.get('email', '').lower()
                    user_name = user_profile.get('name', '').lower()
                    
                    if (username.lower() in author_name or 
                            username.lower() in committer_name or
                            (user_email and user_email == author_email) or
                            (user_name and (user_name in author_name or user_name in committer_name))):
                        
                        key = f"commit-{commit['id']}"
                        if key in seen:
                            continue
                        seen.add(key)
                        
                        commit_date = commit.get('created_at') or commit.get('committed_date')
                        if commit_date and commit_date.startswith(date_str):
                            grouped['pushes'].append({
                                'action': 'commit',
                                'branch': commit.get('ref_name', commit.get('refs', ['unknown'])[0] if commit.get('refs') else 'unknown'),
                                'project': project_name,
                                'timestamp': commit_date,
                                'commit_count': 1,
                                'link': f"{base_url}/projects/{project_id}/commit/{commit['id']}"
                            })
            
            # 2. Try direct push events
            push_url = f"{self.base_url}/projects/{project_id}/events"
            push_params = {
                'action': 'pushed',
                'after': date_str + 'T00:00:00Z',
                'before': next_day_date_str + 'T00:00:00Z',
                'per_page': 50
            }
            
            push_resp = self.safe_get(push_url, params=push_params)
            if push_resp and push_resp.status_code == 200:
                for event in push_resp.json():
                    if event.get('author_id') != user_id and event.get('author', {}).get('id') != user_id:
                        continue
                    
                    created_at = event.get('created_at')
                    if not created_at or not created_at.startswith(date_str):
                        continue
                    
                    push_data = event.get('push_data', {})
                    key = f"push-event-{push_data.get('ref')}-{created_at}"
                    if key in seen:
                        continue
                    seen.add(key)
                    
                    grouped['pushes'].append({
                        'action': 'pushed',
                        'branch': push_data.get('ref'),
                        'project': project_name,
                        'timestamp': created_at,
                        'commit_count': push_data.get('commit_count', 1),
                        'link': f"{base_url}/projects/{project_id}/commits"
                    })
        except Exception as e:
            print(f"[WARNING] Error fetching pushes/commits: {str(e)}")
    
    def _fetch_merge_requests(self, project_id, project_name, base_url, date_str, next_day_date_str, username, seen, grouped):
        """Fetch all merge requests for a project"""
        try:
            mr_url = f"{self.base_url}/projects/{project_id}/merge_requests"
            mr_params = {
                'author_username': username,
                'updated_after': date_str + 'T00:00:00Z',
                'updated_before': next_day_date_str + 'T00:00:00Z',
                'per_page': 50
            }
            
            mr_resp = self.safe_get(mr_url, params=mr_params)
            if mr_resp and mr_resp.status_code == 200:
                for mr in mr_resp.json():
                    key = f"mr-{mr['iid']}-{mr['updated_at']}"
                    if key in seen:
                        continue
                    seen.add(key)
                    
                    # Determine action based on dates
                    action = 'updated'
                    created_at = mr.get('created_at', '')
                    if created_at and created_at.startswith(date_str):
                        action = 'opened'
                    
                    grouped['merge_requests'].append({
                        'action': action,
                        'title': mr['title'],
                        'iid': mr['iid'],
                        'project': project_name,
                        'timestamp': mr['updated_at'],
                        'link': f"{base_url}/projects/{project_id}/merge_requests/{mr['iid']}"
                    })
        except Exception as e:
            print(f"[WARNING] Error fetching merge requests: {str(e)}")
    
    def _fetch_issues(self, project_id, project_name, base_url, date_str, next_day_date_str, username, seen, grouped):
        """Fetch all issues for a project"""
        try:
            # Get issues created by current user
            issue_url = f"{self.base_url}/projects/{project_id}/issues"
            issue_params = {
                'author_username': username,  # Only issues created by current user
                'updated_after': date_str + 'T00:00:00Z',
                'updated_before': next_day_date_str + 'T00:00:00Z',
                'per_page': 50
            }
            
            issue_resp = self.safe_get(issue_url, params=issue_params)
            if issue_resp and issue_resp.status_code == 200:
                for issue in issue_resp.json():
                    key = f"issue-{issue['iid']}-{issue['updated_at']}"
                    if key in seen:
                        continue
                    seen.add(key)
                    
                    # Check if created on the target date
                    created_at = issue.get('created_at', '')
                    closed_at = issue.get('closed_at', '')
                    
                    # Determine action type based on dates
                    action = 'updated'
                    if created_at and created_at.startswith(date_str):
                        action = 'opened'
                    elif closed_at and closed_at.startswith(date_str):
                        action = 'closed'
                    
                    grouped['issues'].append({
                        'action': action,
                        'title': issue['title'],
                        'iid': issue['iid'],
                        'project': project_name,
                        'timestamp': created_at if action == 'opened' else (closed_at if action == 'closed' else issue['updated_at']),
                        'link': f"{base_url}/projects/{project_id}/issues/{issue['iid']}"
                    })
            
            # Get issues closed by the current user (we need a more specific approach to identify who closed an issue)
            user_id = self.get_user_id()
            
            # First, get all closed issues in the date range
            closed_issue_url = f"{self.base_url}/projects/{project_id}/issues"
            closed_issue_params = {
                'state': 'closed',
                'updated_after': date_str + 'T00:00:00Z',
                'updated_before': next_day_date_str + 'T00:00:00Z',
                'per_page': 50
            }
            
            closed_resp = self.safe_get(closed_issue_url, params=closed_issue_params)
            if closed_resp and closed_resp.status_code == 200:
                for issue in closed_resp.json():
                    # Only include issues closed on this specific day
                    closed_at = issue.get('closed_at', '')
                    if not closed_at or not closed_at.startswith(date_str):
                        continue
                    
                    # Now check if we can determine if the current user closed it by checking resource events
                    events_url = f"{self.base_url}/projects/{project_id}/issues/{issue['iid']}/resource_events"
                    events_resp = self.safe_get(events_url)
                    
                    # Check if the current user was the one who closed the issue
                    was_closed_by_user = False
                    if events_resp and events_resp.status_code == 200:
                        for event in events_resp.json():
                            # Look for a 'closed' action by the current user around the closed_at time
                            if (event.get('action') == 'closed' and 
                                event.get('user', {}).get('id') == user_id and
                                event.get('created_at', '').startswith(date_str)):
                                was_closed_by_user = True
                                break
                    
                    # If we couldn't determine from events, skip this issue
                    if not was_closed_by_user:
                        continue
                    
                    key = f"issue-closed-{issue['iid']}-{closed_at}"
                    if key in seen:
                        continue
                    seen.add(key)
                    
                    grouped['issues'].append({
                        'action': 'closed',
                        'title': issue['title'],
                        'iid': issue['iid'],
                        'project': project_name,
                        'timestamp': closed_at,
                        'link': f"{base_url}/projects/{project_id}/issues/{issue['iid']}"
                    })
        except Exception as e:
            print(f"[WARNING] Error fetching issues: {str(e)}")

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