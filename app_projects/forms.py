from django import forms
from django.db.models import Q

from appEmp.models import empProfile

from .models import Project


class LeadChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.user.get_full_name() or obj.user.username


class ProjectForm(forms.ModelForm):
    lead = LeadChoiceField(
        queryset=empProfile.objects.none(), required=False, empty_label="No lead"
    )

    class Meta:
        model = Project
        fields = ["name", "code", "description", "status", "lead", "start_date", "end_date"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "code": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. PRY"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "start_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d"
            ),
            "end_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d"
            ),
        }

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        self.instance.organization_id = organization.pk
        leads = empProfile.objects.filter(organization=organization).filter(
            Q(is_active=True) | Q(pk=self.instance.lead_id)
        )
        self.fields["lead"].queryset = leads.select_related("user").order_by(
            "user__first_name", "user__last_name"
        )
        self.fields["lead"].widget.attrs["class"] = "form-select"
        self.fields["status"].choices = [
            c for c in Project.STATUS_CHOICES if c[0] != Project.STATUS_ARCHIVED
        ]

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        clash = Project.objects.filter(organization=self.organization, name__iexact=name)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError(
                "A project with this name already exists in your organization."
            )
        return name

    def clean_code(self):
        code = (self.cleaned_data.get("code") or "").strip().upper()
        clash = Project.objects.filter(organization=self.organization, code=code)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError(
                "A project with this code already exists in your organization."
            )
        return code
