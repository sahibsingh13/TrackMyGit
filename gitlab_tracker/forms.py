from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User
from .models import GitLabProfile

class CustomUserCreationForm(UserCreationForm):
    """Custom user registration form with email field"""
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={
        'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500',
        'placeholder': 'you@example.com'
    }))
    
    password1 = forms.CharField(widget=forms.PasswordInput(attrs={
        'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500',
        'placeholder': '••••••••'
    }))
    
    password2 = forms.CharField(widget=forms.PasswordInput(attrs={
        'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500',
        'placeholder': '••••••••'
    }))
    
    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2')
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500',
                'placeholder': 'Your username'
            }),
        }
        
    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
            # Create GitLab profile for new user
            GitLabProfile.objects.create(user=user)
        return user

class CustomLoginForm(AuthenticationForm):
    """Custom login form with styled fields"""
    username = forms.CharField(widget=forms.TextInput(attrs={
        'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500',
        'placeholder': 'Username'
    }))
    
    password = forms.CharField(widget=forms.PasswordInput(attrs={
        'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500',
        'placeholder': '••••••••'
    }))

class GitLabTokenForm(forms.ModelForm):
    """Form for setting or updating GitLab token and host"""
    gitlab_token = forms.CharField(
        label="GitLab Personal Access Token",
        widget=forms.PasswordInput(attrs={
            'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500', 
            'placeholder': 'Enter your GitLab token'
        }),
        help_text="Your token is stored securely and only used for accessing your GitLab activity."
    )
    gitlab_host = forms.CharField(
        label="GitLab Host (API Base URL)",
        required=False,
        initial="https://gitlab.com",
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500',
            'placeholder': 'https://gitlab.com (or your self-hosted domain)'
        }),
        help_text="Change this only if you use a self-hosted GitLab instance."
    )
    class Meta:
        model = GitLabProfile
        fields = ('gitlab_token', 'gitlab_host') 