"""
Forms for joining the library and signing in.

Both forms subclass the ones Django ships rather than being written from
scratch. That is not laziness: Django's versions already run the password
validators, hash the password with the configured hasher, normalise
unicode in the username so two visually identical names cannot both be
registered, and reject usernames that differ only in case. Rewriting any
of that by hand would be a security regression.
"""

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

# get_user_model is used rather than importing accounts.models.User so
# that this file keeps working if the user model is ever swapped, and to
# match the rule the rest of the project follows for user references.
User = get_user_model()


class StudentRegistrationForm(UserCreationForm):
    """
    Public sign up form.

    The role field is deliberately absent. A ModelForm only builds fields
    that Meta.fields names, so role never appears in the HTML and, more
    importantly, is ignored even if somebody posts role=librarian by hand.
    That closes the obvious privilege escalation on this form: the only
    way to become a librarian is for an existing librarian or a superuser
    to grant it in the admin.
    """

    class Meta(UserCreationForm.Meta):
        # Meta is inherited rather than replaced so that field_classes
        # keeps mapping username to UsernameField. That field applies NFKC
        # unicode normalisation, which is what stops a lookalike username
        # built from unusual characters passing as a different account.
        model = User
        fields = ("username", "first_name", "last_name", "email")
        widgets = {
            # autocomplete tokens let a password manager fill the form
            # correctly. They are also the difference between a browser
            # offering to save the credentials and silently ignoring them.
            "first_name": forms.TextInput(attrs={"autocomplete": "given-name"}),
            "last_name": forms.TextInput(attrs={"autocomplete": "family-name"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
        }

    def __init__(self, *args, **kwargs):
        """
        Make both name fields compulsory.

        AbstractUser declares first_name and last_name with blank=True, so
        a ModelForm treats them as optional. A library has to be able to
        say who is holding a book, and a username alone is not enough for
        a librarian looking at a shelf list, so they are required here.
        This is done in __init__ rather than by redeclaring the fields,
        which would discard the model's max_length and verbose name.
        """
        super().__init__(*args, **kwargs)
        for field_name in ("first_name", "last_name"):
            self.fields[field_name].required = True

    def clean_email(self):
        """
        Reject an address already in use, ignoring case.

        The model marks email unique, but the database compares the whole
        string exactly, so Reader@example.com and reader@example.com are
        two different values to it and both would be accepted. They are
        the same mailbox to a mail server, which would mean two accounts
        racing over one password reset link. normalize_email lowercases
        the domain half, which is the part that is genuinely case
        insensitive, and the iexact lookup then catches the rest.

        This form only ever creates accounts, so there is no existing row
        to exclude from the check.
        """
        email = User.objects.normalize_email(self.cleaned_data.get("email", ""))
        if email and User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "An account with this email address already exists.",
                code="email_taken",
            )
        return email

    def save(self, commit=True):
        """
        Save the new account as a student.

        The model already defaults role to student, so this is belt and
        braces rather than the only guard. It is worth having because it
        states the intention in the code path that actually creates public
        accounts: if the model default is ever changed, this form still
        cannot hand out librarian rights.

        commit=False on the parent call returns an unsaved instance with
        the password already hashed, which is the point at which role can
        still be set.
        """
        user = super().save(commit=False)
        user.role = User.Role.STUDENT
        if commit:
            user.save()
            # No many to many field is exposed by this form, so save_m2m
            # has nothing to do, but calling it keeps the contract a
            # ModelForm is expected to honour.
            if hasattr(self, "save_m2m"):
                self.save_m2m()
        return user


class LibraryAuthenticationForm(AuthenticationForm):
    """
    Login form that also reports being rate limited.

    The view stacks two django-ratelimit decorators on its POST handler in
    non blocking mode, so a throttled attempt still reaches this form with
    request.limited set to True. Reading that flag here rather than in the
    view means the message appears in the same place as a wrong password,
    instead of as a bare 403 page.
    """

    # The parent's messages are kept and one more is added.
    error_messages = {
        **AuthenticationForm.error_messages,
        "rate_limited": (
            "Too many sign in attempts. Please wait a few minutes and "
            "try again."
        ),
    }

    def clean(self):
        """
        Stop before authenticating when the limit has been reached.

        Order matters. Raising here means super().clean() never runs, so
        authenticate is never called, so a throttled attacker learns
        nothing at all about whether the password was close. If the check
        came after, every blocked attempt would still be a free guess.

        self.request is populated by LoginView.get_form_kwargs, and the
        rate limit decorator sets request.limited before the view body
        runs, so the flag is already in place by the time this executes.
        """
        if getattr(self.request, "limited", False):
            raise forms.ValidationError(
                self.error_messages["rate_limited"],
                code="rate_limited",
            )
        return super().clean()
