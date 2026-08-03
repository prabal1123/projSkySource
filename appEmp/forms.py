from django import forms
from .models import empProfile
from .models import Attendance

class EmployeeForm(forms.ModelForm):
    class Meta:
        model = empProfile
        fields = [
            "phone_number",
            "address",
            "state",
            "zip_code",
        ]

        widgets = {
            "address": forms.Textarea(
                attrs={"rows": 3}
            ),
        }


class ProfileFormAdmin(forms.ModelForm):
    class Meta:
        model = empProfile
        exclude = ["user"]

        widgets = {
            "date_hired": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}
            ),
            "address": forms.Textarea(
                attrs={"rows": 3, "class": "form-control"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-check-input"
            else:
                field.widget.attrs.setdefault("class", "form-control")


class AttendanceUpdateForm(forms.ModelForm):
    class Meta:
        model = Attendance
        fields = ['status', 'check_in', 'check_out']
        widgets = {
            'check_in': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'check_out': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }


