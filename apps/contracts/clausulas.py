"""El texto del contrato de abonado, una sola vez.

El contrato se entrega en dos formatos: PDF para firmar e imprimir, y Word
para cuando hay que modificar algo antes de firmarlo. Los dos dicen lo mismo
porque los dos leen de aquí.

Ese reparto es el mismo que el reporte de materiales ya declara para sus
cuatro salidas: cada formato decide *cómo* se dibuja, nunca *qué* entra. Si el
texto viviera en cada renderizador, dos copias de una cláusula se separarían
al primer ajuste legal, y entonces dos abonados firmarían cosas distintas
según el botón que pulsó el operador.

Los bloques son pares `(tipo, contenido)` y el vocabulario es corto a
propósito -título, subtítulo, párrafo, cláusula, lista, recuadro, cierre,
firmas-: cuanto menos sepa este módulo de tipografía, menos tendrá que
aprender el siguiente formato que haga falta.

El énfasis va marcado con `<b>...</b>`. ReportLab lo entiende tal cual y Word
lo reparte en tramos; es el único formato que ambos comparten sin que este
módulo tenga que saber de ninguno de los dos.
"""

# El hueco que el sistema no sabe llenar se imprime como la línea en blanco
# que era: se completa a mano sobre el papel.
LINEA_EN_BLANCO = "__________________"


def titulo_del_contrato(datos):
    """Título y subtítulo, con la ciudad de la sede que contrata."""

    subtitulo = "(Internet y/o TV por cable – Régimen post pago)"

    if datos["ciudad"]:
        subtitulo += f" – {datos['ciudad'].upper()}"

    return (
        "CONTRATO DE ABONADO PARA LA PRESTACIÓN DE SERVICIOS PÚBLICOS "
        "DE TELECOMUNICACIONES",
        subtitulo,
    )


def datos_de_las_partes(datos):
    """Los pares etiqueta/valor del recuadro, en dos columnas.

    Se devuelven como datos y no dibujados porque el PDF los pone en una
    tabla con franja azul y Word en la suya: lo que comparten es qué dice
    cada celda.
    """

    empresa = datos["empresa"]

    izquierda = [
        ("Razón Social", empresa.business_name if empresa else "—"),
        ("RUC", empresa.ruc if empresa else "—"),
        ("Oficinas comerciales", datos["oficinas"] or LINEA_EN_BLANCO),
        ("Teléfono", datos["telefono"] or LINEA_EN_BLANCO),
    ]

    derecha = [
        ("Código de contrato", datos["numero"]),
        ("Nombre del cliente", datos["cliente"]),
        (datos["documento_tipo"], datos["documento_numero"]),
        ("Dirección de instalación", datos["direccion"]),
        ("Servicio contratado", datos["servicio"]),
        (
            "Fecha de suscripción",
            f"{datos['fecha_suscripcion']:%d/%m/%Y}"
            if datos["fecha_suscripcion"]
            else LINEA_EN_BLANCO,
        ),
        (
            "Última fecha de pago",
            f"{datos['ultima_fecha_de_pago']:%d/%m/%Y}"
            if datos["ultima_fecha_de_pago"]
            else LINEA_EN_BLANCO,
        ),
    ]

    return izquierda, derecha


def bloques_del_contrato(datos):
    """El contrato entero, bloque a bloque, con los huecos ya rellenos.

    Las cláusulas van transcritas del contrato vigente palabra por palabra:
    es un documento con efectos legales, no un resumen de lo que dice.
    """

    empresa = datos["empresa"]
    razon_social = empresa.business_name if empresa else "—"
    ruc = empresa.ruc if empresa else "—"

    ciudad = datos["ciudad"] or LINEA_EN_BLANCO
    velocidad = datos["velocidad"] or LINEA_EN_BLANCO

    bloques = [
        (
            "parrafo",
            "Conste por el presente documento, el contrato de prestación de "
            'servicios públicos de telecomunicaciones (en adelante, "EL '
            'SERVICIO"), que celebran, de una parte, '
            f"<b>{razon_social}</b>, identificada con RUC N.º {ruc}, con "
            f"domicilio legal en {datos['domicilio_legal']} (en adelante, "
            '"LA EMPRESA"), y, de la otra parte, el cliente identificado en '
            'el recuadro siguiente (en adelante, "EL ABONADO"), quienes '
            "acuerdan sujetarse a los siguientes términos y condiciones:",
        ),
        ("recuadro", None),

        ("clausula", "CLÁUSULA PRIMERA: OBJETO DEL CONTRATO"),
        (
            "parrafo",
            "LA EMPRESA se obliga a prestar a EL ABONADO el servicio público "
            "de distribución de radiodifusión por cable (TV) y/o acceso a "
            "Internet, según el plan tarifario contratado y detallado en el "
            "Anexo correspondiente, en el domicilio de instalación declarado "
            "por EL ABONADO.",
        ),

        (
            "clausula",
            "CLÁUSULA SEGUNDA: CARACTERÍSTICAS DEL SERVICIO Y VELOCIDAD "
            "(OSIPTEL)",
        ),
        (
            "parrafo",
            "Para el servicio de acceso a Internet, LA EMPRESA garantiza una "
            "<b>Velocidad Mínima Garantizada (VMG)</b> equivalente al "
            "<b>70%</b> de la velocidad máxima contratada, conforme al "
            "umbral vigente establecido por <b>OSIPTEL</b> en aplicación de "
            "la Ley N.º 31207 y la Resolución de Consejo Directivo "
            "N.º 138-2021-CD/OSIPTEL. Esta garantía se mide sobre la "
            "conexión alámbrica (cable de red UTP/patch cord conectado "
            "directamente al puerto LAN del router/ONT) y no asegura "
            "velocidades exactas vía Wi-Fi, debido a variables de "
            "interferencia externa, barreras físicas e infraestructura "
            "interna del domicilio de EL ABONADO.",
        ),
        (
            "lista",
            (
                False,
                [
                    f"Plan contratado: <b>{velocidad}</b> Mbps (Megabits por "
                    "segundo).",

                    "Para el servicio de TV por cable: se incluye la "
                    "instalación para <b>dos (2) puntos de TV</b>. Todo punto "
                    "adicional requerirá el pago de una tarifa de instalación "
                    "y una tarifa mensual complementaria, según el tarifario "
                    "vigente.",
                ],
            ),
        ),

        (
            "clausula",
            "CLÁUSULA TERCERA: TARIFAS, FACTURACIÓN Y CONDICIONES DE PAGO",
        ),
        (
            "lista",
            (
                True,
                [
                    "Instalación: EL ABONADO abonará por única vez la suma de "
                    f"S/ <b>{datos['instalacion']:.2f}</b> por concepto de "
                    "instalación. Este pago cubre hasta <b>100 metros de "
                    "cable de fibra óptica (Drop)</b>; para la instalación de "
                    "Internet se emplea hasta <b>30 m de cable UTP Cat. 6</b> "
                    "y, para el servicio dúo, hasta <b>50 m de cable "
                    "coaxial</b>. Cualquier metraje que exceda estos límites "
                    "será cotizado, comunicado a EL ABONADO y facturado como "
                    "costo adicional.",

                    "Mensualidad: la tarifa mensual por el servicio "
                    f"contratado es de S/ <b>{datos['mensualidad']:.2f}</b>. "
                    "LA EMPRESA se reserva el derecho de modificar las "
                    "tarifas del servicio, comprometiéndose a comunicarlo a "
                    "EL ABONADO con no menos de treinta (30) días calendario "
                    "de anticipación, conforme a la normativa de OSIPTEL.",

                    "Ciclo de facturación: el ciclo de facturación tiene una "
                    "duración exacta de un (1) mes, iniciando el mismo día en "
                    "que el servicio es instalado y habilitado "
                    "comercialmente. La fecha de vencimiento y cierre de "
                    "facturación corresponderá al último día de dicho ciclo "
                    "mensual.",

                    "Bono por pronto pago (descuento promocional): si EL "
                    "ABONADO realiza el pago de su mensualidad con una "
                    "anticipación mínima de tres (3) días antes de su fecha "
                    "de vencimiento, LA EMPRESA aplicará automáticamente un "
                    "descuento promocional sobre su tarifa mensual regular. "
                    "El monto será de acuerdo al plan contratado. Válido solo "
                    "para internet y dúo.",

                    "Corte automático por morosidad: al finalizar el mes de "
                    "servicio brindado, si EL ABONADO no ha cancelado el "
                    "íntegro de la facturación hasta el último día de su "
                    "ciclo, LA EMPRESA procederá con la <b>suspensión del "
                    "servicio</b>, sin periodos de gracia adicionales.",

                    "Reconexión: la reactivación del servicio originada por "
                    "un corte por morosidad generará un cobro administrativo "
                    "por reconexión, conforme al tarifario vigente al momento "
                    "del evento (tarifa base referencial actual: "
                    "<b>S/ 15.00</b>).",

                    "Límite de instalación y trabajos adicionales: la tarifa "
                    "de instalación estándar cubre exclusivamente el tendido "
                    "del cableado externo, la provisión del equipo terminal "
                    "(Router/ONT) y la configuración para brindar acceso a "
                    "Internet hasta un (1) único punto físico o la "
                    "habilitación de la señal Wi-Fi base del equipo. Todo "
                    "requerimiento de red interna adicional (cableado "
                    "estructurado, canaletas, perforaciones, cableado hacia "
                    "habitaciones adicionales, repetidores Wi-Fi o sistemas "
                    'Mesh) constituye un "Servicio de Red Interna", el cual '
                    "será cotizado de forma independiente y facturado como "
                    "costo adicional, a cancelarse al contado al finalizar la "
                    "instalación.",
                ],
            ),
        ),

        ("clausula", "CLÁUSULA CUARTA: EQUIPOS EN COMODATO Y RESPONSABILIDAD"),
        (
            "parrafo",
            "Los equipos terminales (Router, ONT, Decodificadores), cableado "
            "y accesorios suministrados e instalados por LA EMPRESA se "
            "entregan a EL ABONADO en <b>calidad de comodato (préstamo de "
            "uso)</b>, manteniendo LA EMPRESA la titularidad de los mismos.",
        ),
        (
            "parrafo",
            "Al término, resolución o cancelación de este contrato, EL "
            "ABONADO se obliga a devolver los equipos en óptimas condiciones "
            "operativas. En caso de pérdida, hurto, manipulación indebida, "
            "daño por negligencia (incluyendo cortocircuitos por variaciones "
            "eléctricas del domicilio) o negativa a devolverlos, EL ABONADO "
            "deberá cancelar a LA EMPRESA el <b>valor de reposición del "
            "equipo</b>, conforme al Anexo de Valorización de Equipos vigente "
            "a la fecha del incidente, el cual será entregado a EL ABONADO "
            "junto con este contrato y estará también disponible en las "
            "oficinas comerciales de LA EMPRESA.",
        ),

        ("clausula", "CLÁUSULA QUINTA: USO ACEPTABLE Y PROHIBICIONES"),
        (
            "parrafo",
            "EL ABONADO se compromete a hacer un <b>uso exclusivamente "
            "lícito y residencial</b> del servicio. Queda prohibido, bajo "
            "pena de resolución del contrato, corte del servicio e inicio de "
            "las acciones legales correspondientes:",
        ),
        (
            "lista",
            (
                False,
                [
                    "Comercializar, ceder, subarrendar, retransmitir o "
                    "revender total o parcialmente el ancho de banda a "
                    "terceros o propiedades colindantes (constitución de WISP "
                    "no autorizado).",

                    "Utilizar el servicio para vulnerar la seguridad de otras "
                    "redes, realizar ciberataques, fraude electrónico, "
                    "minería de criptoactivos no declarada que afecte la red, "
                    "o distribuir/consumir contenido ilegal conforme a las "
                    "leyes peruanas e internacionales, incluyendo material de "
                    "explotación sexual infantil y piratería de derechos de "
                    "autor.",

                    "Manipular los sellos de seguridad, configuraciones "
                    "lógicas o firmware de los equipos propiedad de LA "
                    "EMPRESA.",
                ],
            ),
        ),

        (
            "clausula",
            "CLÁUSULA SEXTA: GARANTÍA DE SERVICIO, SOPORTE TÉCNICO Y COSTOS "
            "POR AVERÍAS FÍSICAS",
        ),
        (
            "lista",
            (
                True,
                [
                    "Garantía y soporte 24/7: LA EMPRESA garantiza a EL "
                    "ABONADO soporte técnico lógico, remoto y de monitoreo de "
                    "red las <b>24 horas del día, los 7 días de la "
                    "semana</b>, mientras el contrato se mantenga activo y "
                    "sin deuda. Las averías atribuibles a la infraestructura "
                    "externa de LA EMPRESA (nodos, cajas NAP, fibra troncal) "
                    "serán resueltas <b>sin costo para EL ABONADO</b>.",

                    "Exclusiones de garantía y cobro de visita técnica: la "
                    "garantía de soporte gratuito no aplica y LA EMPRESA "
                    "facturará una tarifa por visita técnica y reposición de "
                    "materiales cuando la avería sea ocasionada por "
                    "negligencia, manipulación o acción de EL ABONADO, "
                    "terceros en su domicilio o mascotas, incluyendo: ruptura "
                    "o doblez extremo del cable de fibra óptica o patchcord "
                    "por limpieza, remodelaciones o mascotas; daño físico a "
                    "conectores o puertos por manipulación indebida; "
                    "solicitudes de reubicación del equipo terminal que "
                    "impliquen extensión del cableado original; y quemadura "
                    "de equipos por cortocircuitos, supresores de pico "
                    "defectuosos o derrames de líquidos. En todos los casos, "
                    "la causal deberá sustentarse en un diagnóstico técnico "
                    "realizado por personal certificado de LA EMPRESA, el "
                    "cual será comunicado por escrito a EL ABONADO antes de "
                    "efectuar cualquier cobro.",

                    "En los casos descritos en el numeral anterior, EL "
                    "ABONADO deberá cancelar los materiales requeridos "
                    "(cable, conectores, equipos nuevos) al contado al "
                    "finalizar el trabajo, según el tarifario vigente de LA "
                    "EMPRESA.",
                ],
            ),
        ),

        ("clausula", "CLÁUSULA SÉPTIMA: LIMITACIÓN DE RESPONSABILIDAD"),
        (
            "parrafo",
            "LA EMPRESA no será responsable por la degradación, "
            "inestabilidad o interrupción del servicio derivada de caso "
            "fortuito o fuerza mayor, incluyendo desastres naturales, "
            "vandalismo o robo de infraestructura pública, y cortes de "
            "energía prolongados que superen el respaldo (UPS/baterías) de "
            "los nodos de LA EMPRESA. Asimismo, LA EMPRESA podrá realizar "
            "cortes programados por mantenimiento preventivo o correctivo, "
            "previa comunicación a EL ABONADO.",
        ),

        (
            "clausula",
            "CLÁUSULA OCTAVA: PROTECCIÓN DE DATOS PERSONALES Y "
            "COMUNICACIONES COMERCIALES",
        ),
        (
            "parrafo",
            "En cumplimiento de la Ley N.º 29733, Ley de Protección de Datos "
            "Personales, y su Reglamento aprobado por Decreto Supremo N.º "
            "003-2013-JUS, EL ABONADO autoriza a LA EMPRESA a tratar sus "
            "datos personales para la ejecución, facturación y gestión "
            "operativa de este contrato. EL ABONADO podrá ejercer sus "
            "derechos de acceso, rectificación, cancelación y oposición "
            "(derechos ARCO) mediante solicitud escrita en cualquiera de las "
            "oficinas comerciales de LA EMPRESA.",
        ),
        (
            "parrafo",
            "Asimismo, mediante su elección expresa, EL ABONADO: "
            "( ) ACEPTA   ( ) NO ACEPTA el uso de sus datos personales para "
            "recibir promociones, ofertas de actualización de planes (Upsell) "
            "y comunicaciones de marketing de las marcas operadas por LA "
            "EMPRESA (Telecable), a través de SMS, WhatsApp, correo "
            "electrónico o llamadas telefónicas.",
        ),

        ("clausula", "CLÁUSULA NOVENA: PLAZO DEL CONTRATO Y RESOLUCIÓN"),
        (
            "parrafo",
            "El presente contrato se celebra a <b>plazo forzoso de seis (6) "
            "meses</b>, en consideración a los costos subsidiados de "
            "instalación e infraestructura de última milla. Superado dicho "
            "plazo, el contrato pasa automáticamente a ser de plazo "
            "indeterminado.",
        ),
        (
            "parrafo",
            "Si EL ABONADO decide resolver el contrato antes del plazo "
            "forzoso, sin causa imputable a LA EMPRESA, deberá cancelar una "
            "<b>penalidad equivalente al saldo no amortizado</b> del subsidio "
            "de instalación otorgado, calculado de forma proporcional a los "
            "meses faltantes del plazo forzoso (Costo de instalación "
            "subsidiado ÷ 6 meses × meses faltantes), monto que será "
            "detallado en el Anexo de Datos. Esta penalidad no podrá exceder "
            "el costo real no amortizado del subsidio otorgado por LA "
            "EMPRESA.",
        ),

        ("clausula", "CLÁUSULA DÉCIMA: PROCEDIMIENTO DE RECLAMOS"),
        (
            "parrafo",
            "EL ABONADO podrá presentar reclamos, quejas o consultas de "
            "manera presencial en las oficinas de LA EMPRESA, mediante el "
            "Libro de Reclamaciones, al correo electrónico "
            "<b>atencion.cliente@telecable.pe</b> o por cualquier otro canal "
            "de atención habilitado por LA EMPRESA.",
        ),
        (
            "parrafo",
            "LA EMPRESA atenderá y responderá el reclamo dentro de los plazos "
            "establecidos por la normativa vigente de <b>OSIPTEL</b>. Si EL "
            "ABONADO no estuviera conforme con la respuesta, podrá presentar "
            "el recurso de apelación correspondiente ante OSIPTEL, de acuerdo "
            "con la normativa aplicable.",
        ),

        ("clausula", "CLÁUSULA UNDÉCIMA: JURISDICCIÓN Y COMPETENCIA"),
        (
            "parrafo",
            "Las partes se someten a las normas emitidas por <b>OSIPTEL</b> "
            "para la resolución de reclamos e instancias administrativas en "
            "materia de telecomunicaciones. Para cualquier controversia legal "
            "no administrativa derivada de la ejecución o interpretación del "
            "presente contrato, las partes se someten a la jurisdicción y "
            f"competencia de los Jueces y Tribunales de la ciudad de "
            f"{ciudad}, Departamento de Junín.",
        ),

        (
            "clausula",
            "CLÁUSULA DUODÉCIMA: SERVICIOS DE VALOR AGREGADO (SVA), "
            "APLICACIONES Y BENEFICIOS PROMOCIONALES",
        ),
        (
            "lista",
            (
                True,
                [
                    "De los beneficios complementarios: según el plan "
                    "contratado, LA EMPRESA podrá otorgar a EL ABONADO acceso "
                    "a aplicaciones de televisión, entretenimiento, seguridad "
                    "o gaming (tales como TCPLAY, Disney+, Kaspersky, "
                    "ExitLag, Cindie, Playkids, Quema Diaria, Zen, Hot Go u "
                    "otros), en calidad de <b>Servicios de Valor Agregado "
                    "(SVA)</b> o beneficios promocionales complementarios.",

                    "Disponibilidad y terceros proveedores: EL ABONADO "
                    "reconoce que dichas aplicaciones son desarrolladas y "
                    "operadas por terceros independientes. LA EMPRESA no "
                    "asume responsabilidad por la disponibilidad técnica, "
                    "caídas de servidor, cambios en las políticas de "
                    "contenido o fallas propias del software de dichos "
                    "terceros.",

                    "Facultad de sustitución o modificación: por razones de "
                    "disponibilidad en el mercado, finalización de convenios "
                    "comerciales o incrementos en los costos de licencias, LA "
                    "EMPRESA podrá modificar, reemplazar o sustituir las "
                    "aplicaciones promocionales por otras de similar valor "
                    "percibido, previa comunicación al cliente con un (1) mes "
                    "de anticipación, sin que esto altere la tarifa base del "
                    "servicio de Internet o TV por cable.",

                    "Condición de puntualidad: el mantenimiento de las "
                    "cuentas activas de las aplicaciones seleccionadas está "
                    "sujeto a que EL ABONADO se encuentre al día en sus "
                    "pagos. La <b>suspensión del servicio</b> por morosidad "
                    "dará lugar a la baja de las licencias asociadas.",
                ],
            ),
        ),
    ]

    if datos["playhub"]:
        correo, celular = datos["playhub"]

        bloques.append(
            (
                "parrafo",
                "Cuenta registrada para las aplicaciones contratadas: "
                f"<b>{correo or LINEA_EN_BLANCO}</b> · "
                f"<b>{celular or LINEA_EN_BLANCO}</b>.",
            )
        )

    bloques.extend(
        [
            (
                "cierre",
                "<b>En señal de conformidad con todos y cada uno de los "
                "términos y condiciones del presente contrato, las partes lo "
                f"suscriben en la ciudad de {ciudad}, a los "
                f"<b>{datos['dia']}</b> días del mes de "
                f"<b>{datos['mes'] or LINEA_EN_BLANCO}</b> de "
                f"{datos['anio']}.</b>",
            ),
            ("firmas", None),
        ]
    )

    return bloques
