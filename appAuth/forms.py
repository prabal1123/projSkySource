from django import forms


class LoginForm(forms.Form):
    username = forms.CharField(
        widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username"})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"})
    )

class registerEmp(forms.Form):
    first_name = forms.CharField(
        widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "given-name"})
    )
    last_name = forms.CharField(
        widget=forms.TextInput(attrs={"autocomplete": "family-name"})
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"autocomplete": "email"})
    )
    
class RequestOTPForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email"})
    )


class VerifyOTPForm(forms.Form):
    otp = forms.CharField(
        max_length=6,
        widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "one-time-code"})
    )