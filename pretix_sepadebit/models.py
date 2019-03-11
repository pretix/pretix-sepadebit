from django.db import models


class SepaExport(models.Model):
    event = models.ForeignKey('pretixbase.Event', related_name='sepa_exports', on_delete=models.CASCADE)
    xmldata = models.TextField()
    datetime = models.DateTimeField(auto_now_add=True)
    testmode = models.BooleanField(default=False)


class SepaExportOrder(models.Model):
    export = models.ForeignKey(SepaExport, on_delete=models.CASCADE)
    order = models.ForeignKey('pretixbase.Order', on_delete=models.CASCADE)
    payment = models.ForeignKey('pretixbase.OrderPayment', on_delete=models.CASCADE, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
