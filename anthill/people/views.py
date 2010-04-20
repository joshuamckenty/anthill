from django.http import HttpResponse
from django.conf import settings
from django.contrib import messages
from django.template import RequestContext
from django.template.loader import render_to_string
from django.shortcuts import redirect, render_to_response, get_object_or_404
from django.views.decorators.http import require_POST
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from anthill.people.models import Profile
from anthill.people.forms import SearchForm, ProfileForm, PasswordForm, UserContactForm
from anthill.people.signals import message_sent

def search(request):
    """
        Location-based search for users.

        Template: people/search.html

        Context:
            form           - ``anthill.people.forms.SearchForm`` instance
            searched       - flag indicating if search has taken place
            search_results - list of search results (may be empty)
    """
    context = { 'form': SearchForm() }

    if request.GET:
        form = SearchForm(request.GET)
        if form.is_valid():
            location = form.cleaned_data['location']
            skills = form.cleaned_data['skills']
            name = form.cleaned_data['name']
            position = form.cleaned_data['position']
            location_range = form.cleaned_data['location_range']

            users = Profile.objects.all().select_related().exclude(user__id=request.user.id)
            if skills:
                tags = [t.strip() for t in skills.split(',')]
                for tag in tags:
                    users = users.filter(skills__icontains=tag)
            if position:
                users = users.filter(role=position)
            if name:
                users = users.filter(user__first_name__icontains=name)
            if location:
                users = users.search_by_distance(location, location_range)
            context = { 'form': form, 'searched': True, 'search_results': users }

    return render_to_response('people/search.html', context,
                             context_instance=RequestContext(request))

def profile(request, username):
    """
        Simple view of user profile.

        Template: people/profile.html

        Context:
            p_user - user to display profile of
    """
    user = get_object_or_404(User, username=username)
    return render_to_response('people/profile.html', {'p_user':user},
                             context_instance=RequestContext(request))

def _user_to_profileform(user):
    """ helper method to convert User/Profile to a populated ProfileForm """
    profile = user.profile
    data = {'name': user.first_name,
            'email': user.email,
            'twitter_id': profile.twitter_id,
            'url': profile.url, 
            'position': profile.role,
            'location': profile.location,
            'skills': profile.skills,
            'about': profile.about}
    return ProfileForm(data)

@login_required
def edit_profile(request):
    """
        Edit profile (and User details) of logged in user.

        Template: people/edit_profile.html

        Context:
            form          - ``ProfileForm``
            password_form - ``anthill.people.forms.PasswordForm``
    """
    password_form = PasswordForm()

    if request.method == 'POST':
        form = ProfileForm(request.POST, request.FILES)
        if form.is_valid():
            user = request.user
            profile = user.profile
            user.first_name = form.cleaned_data['name']
            user.email = form.cleaned_data['email']
            profile.twitter_id = form.cleaned_data['twitter_id']
            profile.url = form.cleaned_data['url']
            profile.role = form.cleaned_data['position']
            profile.location = form.cleaned_data['location']
            profile.skills = form.cleaned_data['skills']
            profile.about = form.cleaned_data['about']
            user.save()
            profile.save()
            messages.success(request, 'Saved profile changes.')
    else:
        form = _user_to_profileform(request.user)
    return render_to_response('people/edit_profile.html', 
                              {'form':form, 'password_form':password_form},
                              context_instance=RequestContext(request))

@login_required
@require_POST
def change_password(request):
    """
        POST endpoint that validates password and redirects to edit_profile
    """
    user = request.user
    password_form = PasswordForm(request.POST)
    form = _user_to_profileform(user)
    if password_form.is_valid():
        user.set_password(password_form.cleaned_data['password1'])
        user.save()
        messages.success(request, 'Password changed.')
        password_form = PasswordForm()
    else:
        messages.success(request, 'Passwords did not match.')
    return redirect('edit_profile')

@login_required
def contact(request, username):
    """
        Contact a user, sending them an email.

        Template: people/contact.html

        Context:
            form    - ``anthill.people.forms.ContactForm``
            to_user - user that the message is being sent to
    """
    to_user = get_object_or_404(User, username=username)

    # only users with a valid email can send email
    if not request.user.email:
        messages.warning(request, 'You must set a valid email address prior to emailing other users.')
        return redirect('edit_profile')

    # if this user can't send email inform them of the fact
    if not request.user.profile.can_send_email():
        messages.warning(request, 'You have currently exceeded the message quota.  Please wait a few minutes before sending this message.')

    if request.method == 'GET':
        form = UserContactForm()
    else:
        form = UserContactForm(request.POST)
        if form.is_valid() and request.user.profile.can_send_email():
            data = {'from_user': request.user, 'to_user': to_user,
                    'subject': form.cleaned_data['subject'],
                    'body': form.cleaned_data['body']}
            subject = render_to_string('people/contact_email_subject.txt', data)
            body = render_to_string('people/contact_email_body.txt', data)
            message_sent.send(sender=request.user, subject=subject, body=body,
                              recipient=to_user)
            to_user.email_user(subject.strip(), body, request.user.email)
            messages.success(request, 'Your email has been delivered to %s' % (to_user.first_name or to_user.username))
            request.user.profile.record_email_sent()
            return redirect('user_profile', username)

    return render_to_response('people/contact.html',
                              {'form': form, 'to_user': to_user},
                              context_instance=RequestContext(request))
