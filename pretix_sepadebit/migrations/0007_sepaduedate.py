# Generated by Django 3.0.14 on 2021-04-22 20:47
from pretix_sepadebit.migrations.sepaduedate_datamigrations import create_sepaduedate_instances, delete_sepaduedate_instances
from django.db import migrations, models
import django.db.models.deletion
import json


def roll_forwards(apps, schema_editor):
    OrderPayment = apps.get_model('pretixbase', 'OrderPayment')
    SepaDueDate = apps.get_model('pretix_sepadebit', 'SepaDueDate')

    create_sepaduedate_instances(OrderPayment, SepaDueDate)


def roll_backwards(apps, schema_editor):
    OrderPayment = apps.get_model('pretixbase', 'OrderPayment')
    SepaDueDate = apps.get_model('pretix_sepadebit', 'SepaDueDate')

    delete_sepaduedate_instances(OrderPayment, SepaDueDate)


class Migration(migrations.Migration):

    dependencies = [
        ('pretixbase', '0181_team_can_checkin_orders'),
        ('pretix_sepadebit', '0006_sepaexport_currency'),
    ]

    operations = [
        migrations.CreateModel(
            name='SepaDueDate',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ('date', models.DateField()),
                ('payment', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='due', to='pretixbase.OrderPayment')),
            ],
        ),
        migrations.RunPython(
            roll_forwards,
            roll_backwards,
        ),
    ]


