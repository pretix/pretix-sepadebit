# Generated by Django 3.2.16 on 2023-01-05 14:14

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('pretixbase', '0226_itemvariationmetavalue'),
        ('pretix_sepadebit', '0007_sepaduedate'),
    ]

    operations = [
        migrations.AlterField(
            model_name='sepaduedate',
            name='payment',
            field=models.OneToOneField(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='sepadebit_due', to='pretixbase.orderpayment'),
        ),
    ]