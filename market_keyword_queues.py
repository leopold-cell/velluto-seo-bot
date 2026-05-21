"""
Velluto SEO Bot — Multi-Market Keyword Queues
Per-market longtail keyword lists for FR, ES, IT, DA, NB, PL, PT-PT, SV.
DE is handled by de_keyword_queue.py (primary content language).
NL is handled by nl_keyword_queue.py.

Structure mirrors de_keyword_queue.py:
  keyword, volume_tier (low/medium/high), phase (1/2/3), angle, locale
"""

import json, os

_LOG_DIR = os.path.dirname(os.path.abspath(__file__))


# ── France (fr) ───────────────────────────────────────────────────────────────
FR_KEYWORD_QUEUE = [
    # Phase 1: Longtail, faible concurrence
    {"keyword": "lunettes vélo avec correction", "volume_tier": "medium", "phase": 1, "locale": "fr",
     "angle": "Problème: lunettes normales ne s'adaptent pas au casque. Solution: monture légère 25g sur correction. "
              "USP StradaPro: ajustement universel, plaquettes réglables, 30 jours d'essai."},
    {"keyword": "lunettes cyclisme antibuée", "volume_tier": "low", "phase": 1, "locale": "fr",
     "angle": "Cause: différence de température, montées. Traitement anti-buée + aération. "
              "StradaPro anti-buée en conditions réelles."},
    {"keyword": "lunettes vélo verres interchangeables", "volume_tier": "low", "phase": 1, "locale": "fr",
     "angle": "Click-In en secondes. Verre clair pour pluie/nuit, teinté pour soleil. "
              "Remplace l'achat de deux paires."},
    {"keyword": "lunettes vélo route légères", "volume_tier": "medium", "phase": 1, "locale": "fr",
     "angle": "Pourquoi le poids compte: pression après 3h, glissement, aérodynamisme. "
              "StradaPro 25g vs concurrence 40-60g. Longues distances, cols alpins."},
    {"keyword": "lunettes vtt antibuée", "volume_tier": "medium", "phase": 1, "locale": "fr",
     "angle": "Spécificités VTT: protection latérale, résistance, buée en forêt. "
              "Verres interchangeables clair/teinté selon ombre/soleil."},
    {"keyword": "lunettes gravel 2026", "volume_tier": "low", "phase": 1, "locale": "fr",
     "angle": "Gravel: conditions changeantes, poussière, long horizon. Verres interchangeables. "
              "Contexte: cols pyrénéens, Ardèche, routes du Tour."},
    {"keyword": "lunettes cyclisme photochromiques test", "volume_tier": "medium", "phase": 1, "locale": "fr",
     "angle": "Photochromiques vs verres interchangeables: temps de réaction, tunnel/forêt, poids. "
              "Quand choisir quoi."},
    {"keyword": "lunettes cyclisme femme", "volume_tier": "medium", "phase": 1, "locale": "fr",
     "angle": "Exigences spécifiques: plaquette plus fine, monture légère. Variantes Viola/Arancia. "
              "Pourquoi le système réglable est universel."},
    {"keyword": "alternative Julbo lunettes vélo", "volume_tier": "low", "phase": 1, "locale": "fr",
     "angle": "Comparaison directe: Julbo Aerospeed (220€) vs Velluto StradaPro (149€). "
              "Poids, verres interchangeables, rapport qualité/prix."},
    {"keyword": "lunettes cyclisme protection UV", "volume_tier": "medium", "phase": 1, "locale": "fr",
     "angle": "UV400 = 100% UVA+UVB. Haute montagne, Côte d'Azur, Alpes en été. "
              "Conséquences sans protection. Certification StradaPro."},
    # Phase 2: Volume moyen
    {"keyword": "meilleures lunettes cyclisme 2026", "volume_tier": "medium", "phase": 2, "locale": "fr",
     "angle": "Top 5 testées. Critères: poids, UV, antibuée, prix. StradaPro meilleur rapport qualité-prix."},
    {"keyword": "lunettes cyclisme triathlon", "volume_tier": "low", "phase": 2, "locale": "fr",
     "angle": "Transition T1/T2 rapide. 25g + verres interchangeables. Sans polarisation (LCD Garmin)."},
    # Phase 3: Pillar
    {"keyword": "lunettes cyclisme", "volume_tier": "high", "phase": 3, "locale": "fr",
     "angle": "Guide ultime lunettes cyclisme 2026. Types, verres, matériaux. StradaPro recommandé. "
              "Liens internes vers articles cluster."},
    {"keyword": "lunettes de vélo", "volume_tier": "high", "phase": 3, "locale": "fr",
     "angle": "Guide complet. Différence lunettes sport vs soleil pour vélo. Top 5 modèles. StradaPro."},
]

# ── Spain (es) ────────────────────────────────────────────────────────────────
ES_KEYWORD_QUEUE = [
    # Phase 1: Longtail, baja competencia
    {"keyword": "gafas ciclismo graduadas", "volume_tier": "medium", "phase": 1, "locale": "es",
     "angle": "Problema: gafas normales no encajan con casco. Solución: montura 25g OTG. "
              "StradaPro: almohadillas ajustables, ajuste universal, 30 días de prueba."},
    {"keyword": "gafas ciclismo antiempañamiento", "volume_tier": "low", "phase": 1, "locale": "es",
     "angle": "Causa: diferencia de temperatura, puertos. Tratamiento antiempañamiento + ventilación. "
              "StradaPro probado en puerto del Tourmalet."},
    {"keyword": "gafas ciclismo lentes intercambiables", "volume_tier": "low", "phase": 1, "locale": "es",
     "angle": "Click-In en segundos. Lente transparente para lluvia/noche, ahumada para sol. "
              "Sustituye la compra de dos gafas."},
    {"keyword": "gafas carretera ligeras", "volume_tier": "medium", "phase": 1, "locale": "es",
     "angle": "Por qué el peso importa: presión tras 3h, deslizamiento, aerodinámica. "
              "StradaPro 25g vs competencia 40-60g. Contexto: escaladores, Pyreneos, Sierra Nevada."},
    {"keyword": "gafas ciclismo fotocromáticas test", "volume_tier": "medium", "phase": 1, "locale": "es",
     "angle": "Fotocromáticas vs lentes intercambiables: tiempo reacción, túneles, peso. "
              "Cuándo elegir cada opción."},
    {"keyword": "gafas ciclismo mujer", "volume_tier": "medium", "phase": 1, "locale": "es",
     "angle": "Requisitos específicos: almohadilla más estrecha, montura ligera. Variantes Viola/Arancia. "
              "Por qué el sistema ajustable es universal."},
    {"keyword": "alternativa Spiuk gafas ciclismo", "volume_tier": "low", "phase": 1, "locale": "es",
     "angle": "Comparación directa: Spiuk Jifter (135€) vs Velluto StradaPro (149€). "
              "Peso, lentes intercambiables, calidad-precio."},
    {"keyword": "gafas MTB antiempañamiento", "volume_tier": "medium", "phase": 1, "locale": "es",
     "angle": "MTB: protección lateral, resistencia, empañamiento en bosque. "
              "Lentes intercambiables claro/ahumado según sombra/sol."},
    {"keyword": "gafas ciclismo protección UV", "volume_tier": "medium", "phase": 1, "locale": "es",
     "angle": "UV400 = 100% UVA+UVB. Vuelta a España, verano mediterráneo, alta montaña. "
              "Consecuencias sin protección. Certificación StradaPro."},
    {"keyword": "gafas ciclismo hombre 2026", "volume_tier": "medium", "phase": 1, "locale": "es",
     "angle": "Top 5 modelos masculinos. Ajuste, peso, filtro UV. StradaPro Nero como opción versátil."},
    # Phase 2
    {"keyword": "mejores gafas ciclismo 2026", "volume_tier": "medium", "phase": 2, "locale": "es",
     "angle": "Top 5 probadas. Criterios: peso, UV, antiempañamiento, precio. StradaPro mejor relación calidad-precio."},
    {"keyword": "gafas ciclismo polarizadas o no", "volume_tier": "low", "phase": 2, "locale": "es",
     "angle": "Polarizadas tapan pantallas LCD (Garmin, Di2). Por qué los ciclistas top no usan polarizadas."},
    # Phase 3
    {"keyword": "gafas ciclismo", "volume_tier": "high", "phase": 3, "locale": "es",
     "angle": "Guía definitiva gafas ciclismo 2026. Tipos, lentes, materiales. StradaPro recomendado."},
    {"keyword": "gafas de ciclismo", "volume_tier": "high", "phase": 3, "locale": "es",
     "angle": "Guía completa. Diferencia gafas deporte vs sol para ciclismo. Top 5 modelos."},
]

# ── Italy (it) ────────────────────────────────────────────────────────────────
IT_KEYWORD_QUEUE = [
    # Phase 1: Longtail, bassa competizione
    {"keyword": "occhiali ciclismo da vista", "volume_tier": "medium", "phase": 1, "locale": "it",
     "angle": "Problema: occhiali normali non si adattano al casco. Soluzione: montatura 25g OTG. "
              "StradaPro: naselli regolabili, adattamento universale, 30 giorni di prova."},
    {"keyword": "occhiali ciclismo antiappannamento", "volume_tier": "low", "phase": 1, "locale": "it",
     "angle": "Causa: differenza di temperatura, salite. Trattamento antiappannamento + ventilazione. "
              "StradaPro testato su passo del Gavia e Dolomiti."},
    {"keyword": "occhiali ciclismo lenti intercambiabili", "volume_tier": "low", "phase": 1, "locale": "it",
     "angle": "Click-In in secondi. Lente chiara per pioggia/notte, colorata per sole. "
              "Sostituisce l'acquisto di due occhiali."},
    {"keyword": "occhiali bici strada leggeri", "volume_tier": "medium", "phase": 1, "locale": "it",
     "angle": "Perché il peso conta: pressione dopo 3h, scivolamento, aerodinamica. "
              "StradaPro 25g vs concorrenza 40-60g. Contesto: salitori, Dolomiti, Giro d'Italia."},
    {"keyword": "occhiali ciclismo fotocromatici test", "volume_tier": "medium", "phase": 1, "locale": "it",
     "angle": "Fotocromatici vs lenti intercambiabili: tempo di reazione, gallerie, peso. "
              "Quando scegliere cosa."},
    {"keyword": "occhiali ciclismo donna", "volume_tier": "medium", "phase": 1, "locale": "it",
     "angle": "Requisiti specifici: nasello più stretto, montatura leggera. Varianti Viola/Arancia. "
              "Perché il sistema regolabile è universale."},
    {"keyword": "alternativa Rudy Project occhiali ciclismo", "volume_tier": "low", "phase": 1, "locale": "it",
     "angle": "Confronto diretto: Rudy Project Rydon (200€) vs Velluto StradaPro (149€). "
              "Peso, lenti intercambiabili, rapporto qualità-prezzo."},
    {"keyword": "occhiali MTB antiappannamento", "volume_tier": "medium", "phase": 1, "locale": "it",
     "angle": "MTB: protezione laterale, resistenza, appannamento nel bosco. "
              "Lenti intercambiabili chiaro/colorato secondo ombra/sole."},
    {"keyword": "occhiali ciclismo protezione UV", "volume_tier": "medium", "phase": 1, "locale": "it",
     "angle": "UV400 = 100% UVA+UVB. Dolomiti, Lago di Garda, estate italiana. "
              "Conseguenze senza protezione. Certificazione StradaPro."},
    {"keyword": "occhiali ciclismo gravel 2026", "volume_tier": "low", "phase": 1, "locale": "it",
     "angle": "Gravel: condizioni variabili, polvere, lungo orizzonte. Lenti intercambiabili come soluzione. "
              "Contesto: Toscana, Strade Bianche, Chianti."},
    # Phase 2
    {"keyword": "migliori occhiali ciclismo 2026", "volume_tier": "medium", "phase": 2, "locale": "it",
     "angle": "Top 5 testati. Criteri: peso, UV, antiappannamento, prezzo. StradaPro miglior rapporto qualità-prezzo."},
    {"keyword": "occhiali ciclismo polarizzati o no", "volume_tier": "low", "phase": 2, "locale": "it",
     "angle": "I polarizzati bloccano i display LCD (Garmin, Di2). Perché i ciclisti pro non usano polarizzati."},
    # Phase 3
    {"keyword": "occhiali ciclismo", "volume_tier": "high", "phase": 3, "locale": "it",
     "angle": "Guida definitiva occhiali ciclismo 2026. Tipi, lenti, materiali. StradaPro consigliato."},
    {"keyword": "occhiali da ciclismo", "volume_tier": "high", "phase": 3, "locale": "it",
     "angle": "Guida completa. Differenza occhiali sport vs sole per ciclismo. Top 5 modelli."},
]

# ── Denmark (da) ──────────────────────────────────────────────────────────────
DA_KEYWORD_QUEUE = [
    # Phase 1: Longhale, lav konkurrence
    {"keyword": "cykelbriller med styrke", "volume_tier": "medium", "phase": 1, "locale": "da",
     "angle": "Problem: normale briller passer ikke under cykelhjelm. Løsning: 25g OTG-stel. "
              "StradaPro: justerbare næsepuder, universalt fit, 30 dages prøveperiode."},
    {"keyword": "cykelbriller anti-dug", "volume_tier": "low", "phase": 1, "locale": "da",
     "angle": "Årsag: temperaturforskel, stigninger. Anti-dug-belægning + ventilationshuller. "
              "StradaPro anti-dug i praksis på danske cykelruter."},
    {"keyword": "cykelbriller udskiftelige glas", "volume_tier": "low", "phase": 1, "locale": "da",
     "angle": "Click-In på sekunder. Klart glas til regn/nat, tonet til sol. "
              "Erstatter køb af to briller."},
    {"keyword": "lette cykelbriller landevej", "volume_tier": "low", "phase": 1, "locale": "da",
     "angle": "Hvorfor vægt tæller: trykfornemmelse efter 3h, glidning, aerodynamik. "
              "StradaPro 25g vs konkurrence 40-60g. Langdistance, Sjælland rundt."},
    {"keyword": "fotokromatiske cykelbriller test", "volume_tier": "medium", "phase": 1, "locale": "da",
     "angle": "Fotokromatisk vs udskiftelige glas: reaktionstid, tunneler/skov, vægt. "
              "Hvornår er hvad bedst."},
    {"keyword": "cykelbriller dame 2026", "volume_tier": "medium", "phase": 1, "locale": "da",
     "angle": "Specifikke krav: smalere næsepude, lettere stel. Varianter Viola/Arancia. "
              "Derfor virker justerbart system universalt."},
    {"keyword": "alternativ til Oakley cykelbriller", "volume_tier": "low", "phase": 1, "locale": "da",
     "angle": "Direkte sammenligning: Oakley Jawbreaker (2.500 kr.) vs Velluto StradaPro (1.100 kr.). "
              "Vægt, udskiftelige glas, pris-kvalitet."},
    {"keyword": "cykelbriller UV beskyttelse", "volume_tier": "low", "phase": 1, "locale": "da",
     "angle": "UV400 = 100% UVA+UVB. Danske sommerturer, Bornholm, Alpe d'HuZes. "
              "Konsekvenser uden beskyttelse."},
    # Phase 2
    {"keyword": "bedste cykelbriller 2026", "volume_tier": "medium", "phase": 2, "locale": "da",
     "angle": "Top 5 testet. Kriterier: vægt, UV, anti-dug, pris. StradaPro bedste pris-kvalitet."},
    # Phase 3
    {"keyword": "cykelbriller", "volume_tier": "high", "phase": 3, "locale": "da",
     "angle": "Den ultimative guide til cykelbriller 2026. Typer, glas, materialer. StradaPro anbefalet."},
]

# ── Norway (nb) ───────────────────────────────────────────────────────────────
NB_KEYWORD_QUEUE = [
    # Phase 1: Langhale, lav konkurranse
    {"keyword": "sykkelbriller med styrke", "volume_tier": "medium", "phase": 1, "locale": "nb",
     "angle": "Problem: vanlige briller passer ikke under sykkelhjelm. Løsning: 25g OTG-innfatning. "
              "StradaPro: justerbare neseputer, universell passform, 30 dagers prøvetid."},
    {"keyword": "sykkelbriller tåkefri", "volume_tier": "low", "phase": 1, "locale": "nb",
     "angle": "Årsak: temperaturforskjell, stigninger, regn. Tåkefri-belegg + ventilasjon. "
              "StradaPro testet på norske fjelloverganger."},
    {"keyword": "sykkelbriller utskiftbare glass", "volume_tier": "low", "phase": 1, "locale": "nb",
     "angle": "Click-In på sekunder. Klart glass til regn/natt, tonet til sol. "
              "Erstatter kjøp av to briller."},
    {"keyword": "lette landeveisbriller sykkel", "volume_tier": "low", "phase": 1, "locale": "nb",
     "angle": "Hvorfor vekt betyr noe: trykk etter 3h, glidning, aerodynamikk. "
              "StradaPro 25g vs konkurranse 40-60g. Fjordtur, landevei, Birkebeinerrittet."},
    {"keyword": "fotokromatiske sykkelbriller test", "volume_tier": "medium", "phase": 1, "locale": "nb",
     "angle": "Fotokromatisk vs utskiftbare glass: reaksjonstid, tunneler/skog, vekt. "
              "Når er hva best."},
    {"keyword": "sykkelbriller dame 2026", "volume_tier": "medium", "phase": 1, "locale": "nb",
     "angle": "Spesifikke krav: smalere neseputt, lettere innfatning. Varianter Viola/Arancia. "
              "Justerbart system fungerer universelt."},
    {"keyword": "alternativ Sweet Protection sykkelbriller", "volume_tier": "low", "phase": 1, "locale": "nb",
     "angle": "Direkte sammenligning: Sweet Protection Falline (1.800 kr.) vs Velluto StradaPro (1.500 kr.). "
              "Vekt, utskiftbare glass, pris-kvalitet."},
    {"keyword": "sykkelbriller UV-beskyttelse", "volume_tier": "low", "phase": 1, "locale": "nb",
     "angle": "UV400 = 100% UVA+UVB. Norsk sommer, fjellturer, refleksjon fra asfalt. "
              "Konsekvenser uten beskyttelse."},
    # Phase 2
    {"keyword": "beste sykkelbriller 2026", "volume_tier": "medium", "phase": 2, "locale": "nb",
     "angle": "Topp 5 testet. Kriterier: vekt, UV, tåkefri, pris. StradaPro beste pris-kvalitet."},
    # Phase 3
    {"keyword": "sykkelbriller", "volume_tier": "high", "phase": 3, "locale": "nb",
     "angle": "Den ultimate guiden til sykkelbriller 2026. Typer, glass, materialer. StradaPro anbefalt."},
]

# ── Poland (pl) ───────────────────────────────────────────────────────────────
PL_KEYWORD_QUEUE = [
    # Phase 1: Longtail, niska konkurencja
    {"keyword": "okulary rowerowe korekcyjne", "volume_tier": "medium", "phase": 1, "locale": "pl",
     "angle": "Problem: zwykłe okulary nie pasują pod kask. Rozwiązanie: 25g oprawa OTG. "
              "StradaPro: regulowane noski, uniwersalne dopasowanie, 30 dni próby."},
    {"keyword": "okulary rowerowe przeciwmgielne", "volume_tier": "low", "phase": 1, "locale": "pl",
     "angle": "Przyczyna: różnica temperatur, podjazdy, deszcz. Powłoka antyparująca + wentylacja. "
              "StradaPro przetestowane na polskich trasach szosowych."},
    {"keyword": "okulary rowerowe wymienne szkła", "volume_tier": "low", "phase": 1, "locale": "pl",
     "angle": "Click-In w sekundach. Przezroczyste szkło na deszcz/noc, przyciemniane na słońce. "
              "Zastępuje zakup dwóch par okularów."},
    {"keyword": "okulary szosowe lekkie", "volume_tier": "low", "phase": 1, "locale": "pl",
     "angle": "Dlaczego waga ma znaczenie: ucisk po 3h, zsuwanie, aerodynamika. "
              "StradaPro 25g vs konkurencja 40-60g. Długie trasy, Bieszczady, Tatry."},
    {"keyword": "okulary rowerowe fotochromowe test", "volume_tier": "medium", "phase": 1, "locale": "pl",
     "angle": "Fotochromowe vs wymienne szkła: czas reakcji, tunele/las, waga. "
              "Kiedy co wybrać."},
    {"keyword": "okulary rowerowe damskie 2026", "volume_tier": "medium", "phase": 1, "locale": "pl",
     "angle": "Specyficzne wymagania: węższy nosek, lżejsza oprawa. Warianty Viola/Arancia. "
              "System regulacji pasuje każdemu."},
    {"keyword": "alternatywa GOG okulary rowerowe", "volume_tier": "low", "phase": 1, "locale": "pl",
     "angle": "Bezpośrednie porównanie: GOG Steno (250 zł) vs Velluto StradaPro (680 zł). "
              "Waga, wymienne szkła, jakość-cena dla kolarza szosowego."},
    {"keyword": "okulary rowerowe ochrona UV", "volume_tier": "medium", "phase": 1, "locale": "pl",
     "angle": "UV400 = 100% UVA+UVB. Polskie lato, Bałtyk, Tatry. "
              "Skutki bez ochrony. Certyfikacja StradaPro."},
    {"keyword": "okulary MTB rowerowe 2026", "volume_tier": "medium", "phase": 1, "locale": "pl",
     "angle": "Wymagania MTB: ochrona boczna, trwałość, zamglenie w lesie. "
              "Wymienne szkła: przezroczyste/przyciemniane w zależności od trasy."},
    # Phase 2
    {"keyword": "najlepsze okulary rowerowe 2026", "volume_tier": "medium", "phase": 2, "locale": "pl",
     "angle": "Top 5 przetestowane. Kryteria: waga, UV, antyparujące, cena. StradaPro najlepsza relacja jakości do ceny."},
    # Phase 3
    {"keyword": "okulary rowerowe", "volume_tier": "high", "phase": 3, "locale": "pl",
     "angle": "Kompletny przewodnik po okularach rowerowych 2026. Typy, szkła, materiały. StradaPro polecane."},
    {"keyword": "okulary kolarskie", "volume_tier": "medium", "phase": 3, "locale": "pl",
     "angle": "Przewodnik po okularach kolarskich 2026. Różnica: MTB vs szosa. Top 5 modeli."},
]

# ── Portugal (pt-PT) ──────────────────────────────────────────────────────────
PT_KEYWORD_QUEUE = [
    # Phase 1: Longtail, baixa concorrência
    {"keyword": "óculos ciclismo graduados", "volume_tier": "medium", "phase": 1, "locale": "pt-PT",
     "angle": "Problema: óculos normais não cabem sob capacete. Solução: armação 25g OTG. "
              "StradaPro: plaquetas nasais ajustáveis, encaixe universal, 30 dias de prova."},
    {"keyword": "óculos ciclismo antiembaciamento", "volume_tier": "low", "phase": 1, "locale": "pt-PT",
     "angle": "Causa: diferença de temperatura, subidas, chuva. Revestimento antiembaciamento + ventilação. "
              "StradaPro testado em rotas do Algarve e Serra da Estrela."},
    {"keyword": "óculos ciclismo lentes intercambiáveis", "volume_tier": "low", "phase": 1, "locale": "pt-PT",
     "angle": "Click-In em segundos. Lente transparente para chuva/noite, colorida para sol. "
              "Substitui a compra de dois óculos."},
    {"keyword": "óculos estrada leves ciclismo", "volume_tier": "low", "phase": 1, "locale": "pt-PT",
     "angle": "Por que o peso importa: pressão após 3h, deslizamento, aerodinâmica. "
              "StradaPro 25g vs concorrência 40-60g. Volta a Portugal, Serra, Douro."},
    {"keyword": "óculos ciclismo fotocromáticos test", "volume_tier": "medium", "phase": 1, "locale": "pt-PT",
     "angle": "Fotocromáticos vs lentes intercambiáveis: tempo de reação, túneis, peso. "
              "Quando escolher cada opção."},
    {"keyword": "óculos ciclismo mulher 2026", "volume_tier": "medium", "phase": 1, "locale": "pt-PT",
     "angle": "Requisitos específicos: plaqueta mais estreita, armação leve. Variantes Viola/Arancia. "
              "Sistema regulável funciona universalmente."},
    {"keyword": "alternativa Spiuk óculos ciclismo", "volume_tier": "low", "phase": 1, "locale": "pt-PT",
     "angle": "Comparação direta: Spiuk Jifter (130€) vs Velluto StradaPro (149€). "
              "Peso, lentes intercambiáveis, custo-benefício."},
    {"keyword": "óculos ciclismo proteção UV", "volume_tier": "medium", "phase": 1, "locale": "pt-PT",
     "angle": "UV400 = 100% UVA+UVB. Algarve, Alentejo, verão português. "
              "Consequências sem proteção. Certificação StradaPro."},
    # Phase 2
    {"keyword": "melhores óculos ciclismo 2026", "volume_tier": "medium", "phase": 2, "locale": "pt-PT",
     "angle": "Top 5 testados. Critérios: peso, UV, antiembaciamento, preço. StradaPro melhor custo-benefício."},
    # Phase 3
    {"keyword": "óculos ciclismo", "volume_tier": "high", "phase": 3, "locale": "pt-PT",
     "angle": "Guia definitivo óculos ciclismo 2026. Tipos, lentes, materiais. StradaPro recomendado."},
    {"keyword": "óculos de ciclismo", "volume_tier": "high", "phase": 3, "locale": "pt-PT",
     "angle": "Guia completo. Diferença óculos desporto vs sol para ciclismo. Top 5 modelos."},
]

# ── Sweden (sv) ───────────────────────────────────────────────────────────────
SV_KEYWORD_QUEUE = [
    # Phase 1: Longtail, låg konkurrens
    {"keyword": "cykelglasögon med styrka", "volume_tier": "medium", "phase": 1, "locale": "sv",
     "angle": "Problem: vanliga glasögon passar inte under cykelhjälm. Lösning: 25g OTG-båge. "
              "StradaPro: justerbara näsbryggor, universell passform, 30 dagars provperiod."},
    {"keyword": "cykelglasögon dimmfritt", "volume_tier": "low", "phase": 1, "locale": "sv",
     "angle": "Orsak: temperaturskillnad, stigningar, regn. Dimmfri beläggning + ventilation. "
              "StradaPro testat på Vätternrundan och svenska skogsvägar."},
    {"keyword": "cykelglasögon utbytbara glas", "volume_tier": "low", "phase": 1, "locale": "sv",
     "angle": "Click-In på sekunder. Klart glas för regn/natt, tonat för sol. "
              "Ersätter köp av två glasögon."},
    {"keyword": "landsvägsglasögon cykling", "volume_tier": "low", "phase": 1, "locale": "sv",
     "angle": "Varför vikt spelar roll: tryckkänsla efter 3h, glidning, aerodynamik. "
              "StradaPro 25g vs konkurrens 40-60g. Vätternrundan, Göta Kanal, fjällvägar."},
    {"keyword": "fotokromatiska cykelglasögon test", "volume_tier": "medium", "phase": 1, "locale": "sv",
     "angle": "Fotokromatiska vs utbytbara glas: reaktionstid, tunnlar/skog, vikt. "
              "När är vad bäst."},
    {"keyword": "cykelglasögon dam 2026", "volume_tier": "medium", "phase": 1, "locale": "sv",
     "angle": "Specifika krav: smalare näsbrygga, lättare båge. Varianter Viola/Arancia. "
              "Justerbart system passar alla."},
    {"keyword": "alternativ Bliz cykelglasögon", "volume_tier": "low", "phase": 1, "locale": "sv",
     "angle": "Direkt jämförelse: Bliz Velo (900 kr.) vs Velluto StradaPro (1.600 kr.). "
              "Vikt, utbytbara glas, pris-prestanda för landsväg."},
    {"keyword": "cykelglasögon UV-skydd", "volume_tier": "low", "phase": 1, "locale": "sv",
     "angle": "UV400 = 100% UVA+UVB. Svensk sommar, fjällcykling, reflektioner från asfalt. "
              "Konsekvenser utan skydd. StradaPro-certifiering."},
    {"keyword": "cykelglasögon MTB 2026", "volume_tier": "medium", "phase": 1, "locale": "sv",
     "angle": "MTB: sidoberäddning, hållbarhet, dimma i skogen. "
              "Utbytbara glas: klart/tonat beroende på skugga/sol."},
    # Phase 2
    {"keyword": "bästa cykelglasögon 2026", "volume_tier": "medium", "phase": 2, "locale": "sv",
     "angle": "Topp 5 testade. Kriterier: vikt, UV, dimmfritt, pris. StradaPro bästa pris-prestanda."},
    # Phase 3
    {"keyword": "cykelglasögon", "volume_tier": "high", "phase": 3, "locale": "sv",
     "angle": "Den ultimata guiden till cykelglasögon 2026. Typer, glas, material. StradaPro rekommenderat."},
]

# ── Registry ──────────────────────────────────────────────────────────────────
MARKET_QUEUES = {
    "fr":    FR_KEYWORD_QUEUE,
    "es":    ES_KEYWORD_QUEUE,
    "it":    IT_KEYWORD_QUEUE,
    "da":    DA_KEYWORD_QUEUE,
    "nb":    NB_KEYWORD_QUEUE,
    "pl":    PL_KEYWORD_QUEUE,
    "pt-PT": PT_KEYWORD_QUEUE,
    "sv":    SV_KEYWORD_QUEUE,
}


def _log_path(locale: str) -> str:
    return os.path.join(_LOG_DIR, f"market_keywords_used_{locale.replace('-', '_')}.json")


def _load_used(locale: str) -> set:
    p = _log_path(locale)
    if not os.path.exists(p):
        return set()
    return set(json.load(open(p)))


def _save_used(locale: str, used: set):
    json.dump(sorted(used), open(_log_path(locale), "w"), indent=2)


def get_next_market_keyword(locale: str) -> dict | None:
    """Return next unused keyword for a specific locale, lowest phase first, highest volume tier first."""
    queue = MARKET_QUEUES.get(locale, [])
    used = _load_used(locale)
    TIER_ORDER = {"high": 0, "medium": 1, "low": 2}
    remaining = [k for k in queue if k["keyword"] not in used]
    if not remaining:
        return None
    remaining.sort(key=lambda k: (k["phase"], TIER_ORDER.get(k.get("volume_tier", "low"), 2)))
    return remaining[0]


def mark_market_keyword_used(locale: str, keyword: str):
    used = _load_used(locale)
    used.add(keyword)
    _save_used(locale, used)


def get_market_queue_status(locale: str) -> dict:
    queue = MARKET_QUEUES.get(locale, [])
    used = _load_used(locale)
    by_phase: dict[str, dict] = {}
    for k in queue:
        p = str(k["phase"])
        if p not in by_phase:
            by_phase[p] = {"total": 0, "done": 0}
        by_phase[p]["total"] += 1
        if k["keyword"] in used:
            by_phase[p]["done"] += 1
    return {
        "locale": locale,
        "total": len(queue),
        "used": len(used),
        "by_phase": by_phase,
    }


def get_all_market_status() -> list[dict]:
    return [get_market_queue_status(loc) for loc in MARKET_QUEUES]
