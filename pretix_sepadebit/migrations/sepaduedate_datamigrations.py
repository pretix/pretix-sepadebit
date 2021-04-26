import json

def create_sepaduedate_instances(OrderPayment, SepaDueDate):
    for op in OrderPayment.objects.filter(provider='sepadebit').filter(info__isnull=False):
        # prevents dependency from the info_data property
        op_info_data = json.loads(op.info)
        due_date = SepaDueDate(date=op_info_data['date'])
        due_date.payment = op
        due_date.save()
        del op_info_data['date']
        op.info = json.dumps(op_info_data, sort_keys=True)
        op.save()

def delete_sepaduedate_instances(OrderPayment, SepaDueDate):
    for due in SepaDueDate.objects.filter(payment__isnull=False):
        order_info_data = json.loads(due.payment.info)
        order_info_data['date'] = due.date.strftime("%Y-%m-%d")
        due.payment.info = json.dumps(order_info_data, sort_keys=True)
        due.payment.save()
        due.delete()