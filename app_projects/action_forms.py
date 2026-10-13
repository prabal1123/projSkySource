from django import forms
from django.db.models import Q

from appEmp.models import empProfile

from .forms import LeadChoiceField


class ActionForm(forms.Form):
    title = forms.CharField(
        max_length=200, widget=forms.TextInput(attrs={"class": "form-control"})
    )
    description = forms.CharField(
        required=False,
        max_length=5000,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 5}),
    )
    assignee = LeadChoiceField(
        queryset=empProfile.objects.none(), required=False, empty_label="Unassigned"
    )
    due_date = forms.DateField(
        required=False,
        widget=forms.DateInput(
            attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d"
        ),
    )

    def __init__(self, *args, project, current_assignee_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        allowed = Q(project=project, is_active=True)
        if current_assignee_id:
            allowed |= Q(pk=current_assignee_id)
        self.fields["assignee"].queryset = (
            empProfile.objects.filter(organization=project.organization)
            .filter(allowed)
            .select_related("user")
            .order_by("user__first_name", "user__last_name")
        )
        self.fields["assignee"].widget.attrs["class"] = "form-select"
