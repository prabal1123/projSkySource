from django import forms
import re

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




class RequestWhatsAppOTPForm(forms.Form):
    phone_number = forms.CharField(
        max_length=20,
        widget=forms.TextInput(attrs={
            "autofocus": True,
            "autocomplete": "tel",
            "placeholder": "e.g. 9812345678",
        }),
    )

    def clean_phone_number(self):
        number = self.cleaned_data["phone_number"].strip()
        number = re.sub(r"[\s\-]", "", number)   # strip spaces/hyphens
        number = number.removeprefix("+91").removeprefix("91") if len(number) > 10 else number
        number = number.lstrip("0")               # in case someone types a leading 0

        if not re.fullmatch(r"\d{10}", number):
            raise forms.ValidationError("Enter a valid 10-digit phone number.")

        return number
    

class VerifyOTPForm(forms.Form):
    otp = forms.CharField(
        max_length=6,
        widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "one-time-code"})
    )

