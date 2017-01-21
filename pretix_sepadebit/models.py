from django.db import models


class SepaExport(models.Model):
    event = models.ForeignKey('pretixbase.Event', related_name='sepa_exports')
    xmldata = models.TextField()
    datetime = models.DateTimeField(auto_now_add=True)
    orders = models.ManyToManyField('pretixbase.Order', related_name='sepa_exports')
