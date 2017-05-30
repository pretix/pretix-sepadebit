from django.db import models


class SepaExport(models.Model):
    event = models.ForeignKey('pretixbase.Event', related_name='sepa_exports')
    xmldata = models.TextField()
    datetime = models.DateTimeField(auto_now_add=True)


class SepaExportOrder(models.Model):
    export = models.ForeignKey(SepaExport)
    order = models.ForeignKey('pretixbase.Order')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
