from django import forms
from .models import empProfile
from .models import Attendance, Salary

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

# ── Add to appEmp/forms.py ──────────────────────────────────────────────

class SalaryForm(forms.ModelForm):
    class Meta:
        model = Salary
        fields = ['basic_salary', 'hra', 'pf', 'effective_date']
        widgets = {
            'effective_date': forms.DateInput(attrs={'type': 'date'}),
            'basic_salary': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'hra': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'pf': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
        }

    def clean_basic_salary(self):
        val = self.cleaned_data['basic_salary']
        if val <= 0:
            raise forms.ValidationError("Basic salary must be greater than zero.")
        return val
