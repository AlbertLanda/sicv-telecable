from django.contrib import admin
from apps.payments.admin import CollectionReadOnlyAdmin
from .models import BankAccount, BankEvent, BankLine, BankMatch, BankStatement

for model in (BankAccount, BankEvent, BankLine, BankMatch, BankStatement):
    admin.site.register(model, CollectionReadOnlyAdmin)
