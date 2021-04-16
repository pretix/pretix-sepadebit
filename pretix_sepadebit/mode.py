from django import forms
from django.utils.translation import gettext_lazy as _

class PaymentMode:
    fields = ['mode_choices', 'prenotification', 'payment_date', 'prenotification_fixed', 'export_days']

    def __init__(self, data_list):
        for i, field in enumerate(self.fields):
            try:
                setattr(self, field, data_list[i])
            except IndexError:
                setattr(self, field, None)

    def to_list(self):
        values=[getattr(self,field) for field in self.fields]
        return values

class PaymentModeWidget(forms.MultiWidget):
    template_name = 'pretix_sepadebit/payment_mode.html'
    def __init__(self, *args, **kwargs):

        widgets = (
            forms.RadioSelect(choices=kwargs.pop('mode_choices')),
            forms.NumberInput(attrs={'placeholder': _('Pre-notification time')}),
            forms.DateInput( attrs={'class': 'datepickerfield', 'placeholder': _('Due date')}),
            forms.NumberInput(attrs={'placeholder': _('Customer pre-notification time')}),
            forms.NumberInput(attrs={'placeholder': _('Download notification time')})

        )
        super().__init__(widgets=widgets, *args, **kwargs)


    def decompress(self, value):
        if value:
            return value.to_list()
        return [None, None, None, None, None]


class PaymentModeField(forms.MultiValueField):


    def __init__(self, *args, **kwargs):
        mode_choices = [
            ('relative_payment', _('Relative date payment')),
            ('fixed_payment', _('Fixed date payment')),
        ]

        fields=(
            forms.ChoiceField(
                choices=mode_choices,
                required=True
            ),
            forms.IntegerField(
                required=False
            ),
            forms.DateField(
                required=False
            ),
            forms.IntegerField(
                required=False,
                help_text=_('We will use this string and append the event slug and the order code to build a unique SEPA mandate reference.'),
            ),
            forms.IntegerField(
                required=False,
                help_text="This is the grey text"
            ),
        )

        if 'widget' not in kwargs:
            kwargs['widget'] = PaymentModeWidget(mode_choices=mode_choices)

        super().__init__(
            fields=fields, require_all_fields=False, *args, **kwargs
        )

    def compress(self, data_list):
        if not data_list:
            return None
        else:
            return PaymentMode(data_list)

    def clean(self, value):
        return super().clean(value)
