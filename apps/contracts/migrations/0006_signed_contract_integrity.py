from django.db import migrations, models
import apps.contracts.models


class Migration(migrations.Migration):

    dependencies = [
        ("contracts", "0005_colocacion_de_la_firma"),
    ]

    operations = [
        migrations.AddField(
            model_name="contractsignature",
            name="signed_pdf",
            field=models.FileField(
                blank=True,
                help_text=(
                    "Copia inmutable del documento aceptado por el abonado. "
                    "Una vez firmado, las descargas oficiales leen este archivo."
                ),
                upload_to=apps.contracts.models.signed_contract_pdf_path,
                verbose_name="PDF firmado definitivo",
            ),
        ),
        migrations.AddField(
            model_name="contractsignature",
            name="signed_pdf_sha256",
            field=models.CharField(
                blank=True,
                editable=False,
                max_length=64,
                verbose_name="SHA-256 del PDF firmado",
            ),
        ),
        migrations.AddField(
            model_name="contractsignature",
            name="signed_pdf_created_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                null=True,
                verbose_name="PDF firmado archivado el",
            ),
        ),
        migrations.AddField(
            model_name="contractsignature",
            name="document_anchor",
            field=models.JSONField(
                blank=True,
                default=dict,
                editable=False,
                verbose_name="Ancla de firma del documento",
            ),
        ),
        migrations.AddConstraint(
            model_name="contract",
            constraint=models.UniqueConstraint(
                condition=models.Q(is_active=True),
                fields=("subscription",),
                name="unique_active_contract_per_subscription",
            ),
        ),
    ]
}
