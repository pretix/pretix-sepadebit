from django.db import models
from django.utils.translation import gettext_lazy as _, pgettext_lazy

class SepaExport(models.Model):
    event = models.ForeignKey('pretixbase.Event', related_name='sepa_exports', on_delete=models.CASCADE, null=True, blank=True)
    organizer = models.ForeignKey('pretixbase.Organizer', related_name='sepa_exports', on_delete=models.PROTECT, null=True, blank=True)
    xmldata = models.TextField()
    datetime = models.DateTimeField(auto_now_add=True)
    testmode = models.BooleanField(default=False)
    currency = models.CharField(max_length=9, blank=True)


class SepaExportOrder(models.Model):
    export = models.ForeignKey(SepaExport, on_delete=models.CASCADE)
    order = models.ForeignKey('pretixbase.Order', on_delete=models.CASCADE)
    payment = models.ForeignKey('pretixbase.OrderPayment', on_delete=models.CASCADE, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)


class SepaDueDate(models.Model):
    REMINDER_OUTSTANDING = "o"
    REMINDER_PROVIDED = "p"
    REMINDER_CHOICE = (
        (REMINDER_OUTSTANDING, _("outstanding")),
        (REMINDER_PROVIDED, _("provided")),
    )

    payment = models.OneToOneField('pretixbase.OrderPayment', on_delete=models.CASCADE, null=True, related_name='due')
    date = models.DateField()
    reminder = models.CharField(
        max_length=1,
        choices=REMINDER_CHOICE,
        verbose_name=_("Reminder"),
        default=REMINDER_PROVIDED
    )
