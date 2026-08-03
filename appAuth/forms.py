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
    username = forms.CharField(
        widget=forms.TextInput(attrs={"autocomplete": "username"})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"})
    )