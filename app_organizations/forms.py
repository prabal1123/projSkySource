from django import forms


class CreateOrganizationForm(forms.Form):
    org_name = forms.CharField(
        label="Organization name",
        max_length=150,
        widget=forms.TextInput(attrs={"autofocus": True}),
    )
    owner_first_name = forms.CharField(
        label="Owner first name",
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )
    owner_last_name = forms.CharField(
        label="Owner last name",
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )
    owner_email = forms.EmailField(
        label="Owner email",
        widget=forms.EmailInput(attrs={"autocomplete": "off"}),
    )
