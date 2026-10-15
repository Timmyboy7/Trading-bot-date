"""Texts for the dashboard in English and German, and number formatting."""
import re

T = {
    "overview": ("Overview", "Übersicht"), "holdings": ("Holdings", "Bestand"), "basket": ("Basket", "Korb"),
    "risk": ("Risk", "Risiko"), "activity": ("Activity", "Aktivität"), "reports": ("Reports", "Berichte"),
    "how": ("How it works", "So funktioniert es"), "profile": ("Profile", "Profil"),
    "sign_in": ("Sign in", "Anmelden"), "sign_out": ("Sign out", "Abmelden"),
    "username": ("Username", "Benutzername"), "password": ("Password", "Passwort"),
    "login_note": ("Family accounts can view everything but change nothing. Forgot your password? Ask Tim.",
                   "Familien-Zugänge sehen alles, können aber nichts ändern. Passwort vergessen? Tim fragen."),
    "login_bad": ("Wrong username or password.", "Benutzername oder Passwort falsch."),
    "login_slow": ("Too many attempts. Please wait 15 minutes.", "Zu viele Versuche. Bitte 15 Minuten warten."),
    "private": ("Private family portfolio.", "Privates Familien-Depot."),
    "owner": ("Owner", "Inhaber"), "viewer": ("View only", "Nur ansehen"),
    "evening": ("Good evening", "Guten Abend"), "morning": ("Good morning", "Guten Morgen"),
    "day": ("Hello", "Hallo"),
    "paper_note": ("Paper account (play money) · updated after each run", "Testkonto (Spielgeld) · nach jedem Lauf aktualisiert"),
    "value": ("Portfolio value", "Depotwert"), "paid_in": ("paid in", "eingezahlt"),
    "on": ("on", "bei"), "vs_spy": ("Versus the S&P 500", "Im Vergleich zum S&P 500"),
    "ahead": ("Ahead by", "Voraus um"), "behind": ("Behind by", "Zurück um"),
    "sc_title": ("Did waiting pay off?", "Hat Abwarten sich gelohnt?"),
    "sc_intro": ("When a timing rule made us skip a buy, we note the price. When the stock is bought later, we compare: positive = bought cheaper than on the day we first waited.", "Wenn eine Timing-Regel einen Kauf aufgeschoben hat, merken wir uns den Kurs. Wird die Aktie später gekauft, vergleichen wir: positiv = billiger gekauft als am ersten Warte-Tag."),
    "sc_rule": ("Rule", "Regel"), "sc_waited": ("Waited", "Gewartet"), "sc_bought": ("Bought later", "Später gekauft"),
    "sc_cheaper": ("Cheaper", "Billiger"), "sc_avg": ("Avg. difference", "Ø Unterschied"), "sc_usd": ("Effect", "Effekt"),
    "sc_still": ("still waiting", "wartet noch"),
    "sc_empty": ("No waits judged yet. Results appear once a skipped stock has been bought.", "Noch keine Wartefälle bewertet. Ergebnisse erscheinen, sobald eine zurückgestellte Aktie gekauft wurde."),
    "sc_caveat": ("{n} case(s) so far. This only means something after many cases (30+). Information only.", "Bisher {n} Fall/Fälle. Aussagekräftig erst nach vielen Fällen (30+). Nur zur Information."),
    "wr_dayDrop": ("Big one-day drop", "Großer Tagesverlust"), "wr_knife": ("Falling knife", "Fallendes Messer"),
    "wr_spike": ("Price spike", "Kurssprung"), "wr_news": ("News / earnings", "News / Quartalszahlen"),
    "close": ("Close", "Schließen"),
    "gain_abs": ("Gain / loss", "Gewinn / Verlust"),
    "checks_label": ("Checked at purchase", "Geprüft beim Kauf"),
    "price": ("Price", "Kurs"), "today": ("Today", "Heute"),
    "inv_title": ("Invested in stocks", "In Aktien investiert"), "put_into": ("put into stocks", "in Aktien eingesetzt"),
    "vs_spy_same": ("Versus the S&P 500, same purchases", "Im Vergleich zum S&P 500, gleiche Käufe"),
    "twin_note": ("Each time we bought a stock, the same dollars would have gone into the S&P 500 at that very moment. Cash is not part of this comparison.",
                  "Bei jedem Aktienkauf wäre derselbe Betrag im selben Moment in den S&P 500 geflossen. Bargeld gehört nicht zu diesem Vergleich."),
    "cash_side": ("Cash on the side", "Bargeld nebenbei"), "cash_side_note": ("Waiting to be invested. Not part of the comparison.", "Wartet aufs Investieren. Nicht Teil des Vergleichs."),
    "whole_acct": ("Whole account", "Gesamtes Depot"), "inv_vs_title": ("Invested money vs the S&P 500", "Investiertes Geld gegen den S&P 500"),
    "put_in": ("Put in", "Eingesetzt"), "our_stocks": ("Our stocks", "Unsere Aktien"),
    "spy_twin_row": ("S&P 500, same purchases", "S&P 500, gleiche Käufe"),
    "whole_line": ("Whole account incl. cash", "Gesamtes Depot inkl. Bargeld"),
    "whole_vs": ("Whole account including cash: {a}, against {b} if all deposits had gone straight into the S&P 500 on day one. That gap mostly shows how much cash is still waiting.",
                 "Gesamtes Depot inklusive Bargeld: {a}, gegen {b}, wenn alle Einzahlungen von Anfang an direkt in den S&P 500 geflossen wären. Der Abstand zeigt vor allem, wie viel Bargeld noch wartet."),
    "live_open": ("Live · {t}", "Live · {t}"), "live_closed": ("Market closed · {t}", "Börse geschlossen · {t}"),
    "split_title": ("Where the money is today", "Wo das Geld heute steckt"),
    "split_inv": ("Invested in stocks", "In Aktien investiert"), "split_cash": ("Cash", "Bargeld"),
    "paid_in_c": ("Paid in", "Eingezahlt"), "worth_now": ("Worth now", "Wert heute"), "growth": ("Growth", "Zuwachs"),
    "our_pf": ("Our portfolio", "Unser Depot"), "spy_row": ("S&P 500, same deposits", "S&P 500, gleiche Einzahlungen"),
    "pf_split": ("Our portfolio: {s} in stocks and {c} in cash.", "Unser Depot: {s} in Aktien und {c} Bargeld."),
    "spy_asof": ("The S&P 500 is counted from the moment of our first purchases. Both are priced live while the market is open, otherwise at the last close.",
                 "Der S&P 500 zählt ab dem Moment unserer ersten Käufe. Beide werden bei geöffneter Börse live bewertet, sonst zum letzten Schlusskurs."),
    "spy_same": ("The same deposits on the same days in an S&P 500 fund would be worth",
                 "Dieselben Einzahlungen an denselben Tagen in einem S&P-500-Fonds wären wert"),
    "started": ("Started", "Gestartet"), "monthly": ("Monthly deposit", "Monatliche Einzahlung"),
    "held": ("Stocks held", "Aktien im Depot"), "of": ("of", "von"), "cash": ("Cash", "Bargeld"),
    "since_start": ("Value since the start", "Wert seit dem Start"),
    "your_basket": ("Your basket", "Unser Depot"), "spy_line": ("S&P 500, same deposits", "S&P 500, gleiche Einzahlungen"),
    "next_decision": ("Next decision", "Nächste Entscheidung"), "daily_check": ("Daily check: news, prices, buys and sells",
                                                                               "Tagesprüfung: Nachrichten, Kurse, Käufe und Verkäufe"),
    "alarm": ("Crash alarm", "Crash-Alarm"), "alarm_text": ("Checked every 30 min while the market is open",
                                                          "Alle 30 Minuten geprüft, solange die Börse offen ist"),
    "tax_hold": ("Inside the 6-month tax hold", "In der 6-Monats-Haltefrist"),
    "tax_free_from": ("First one becomes tax-free on", "Die erste wird steuerfrei am"),
    "next_review": ("Next basket review", "Nächste Korb-Prüfung"), "sunday": ("Sunday, 20:00", "Sonntag, 20:00"),
    "picks20": ("Picks the 20 strongest stocks", "Wählt die 20 stärksten Aktien"),
    "this_week": ("This week in plain words", "Diese Woche, einfach erklärt"), "all_activity": ("All activity", "Alle Aktivitäten"),
    "biggest": ("Biggest positions", "Größte Positionen"), "all_holdings": ("All holdings", "Alle Positionen"),
    "chart_wait": ("The first purchases are in. A line needs at least two days, so the chart starts after tomorrow's close and then grows every day.",
                   "Die ersten Käufe sind erledigt. Für eine Linie braucht es mindestens zwei Tage: Die Grafik beginnt nach dem Handelsschluss morgen und wächst dann täglich."),
    "nothing_yet": ("Nothing has been bought yet. The first purchases appear here after the next daily run.",
                    "Noch nichts gekauft. Die ersten Käufe erscheinen hier nach dem nächsten Tageslauf."),
    "stocks": ("stocks", "Aktien"), "stock": ("Stock", "Aktie"), "gain": ("Gain", "Gewinn"),
    "share": ("Share", "Anteil"), "trend": ("Trend", "Trend"), "next_event": ("Next event", "Nächster Termin"),
    "day_of": ("day {d} of 182", "Tag {d} von 182"), "healthy": ("Healthy", "Gesund"), "watch": ("Watch", "Beobachten"),
    "near_rule": ("Near sell rule", "Nahe Verkaufsregel"),
    "results": ("Results", "Zahlen"), "why_own": ("Why we own it", "Warum wir sie besitzen"),
    "sell_if": ("What would make us sell", "Was uns zum Verkauf bringen würde"),
    "rules_now": ("Safety rules right now", "Schutzregeln im Moment"),
    "above_avg": ("Above its 150-day average", "Über dem 150-Tage-Durchschnitt"),
    "below_high": ("Below its high since purchase", "Unter dem Höchststand seit Kauf"),
    "sell_rule_25": ("sell rule: −25%", "Verkaufsregel: −25 %"), "stop": ("Emergency stop", "Notbremse"),
    "now": ("now", "jetzt"), "tax_free": ("Tax-free from", "Steuerfrei ab"), "yes": ("Yes", "Ja"), "no": ("No", "Nein"),
    "coming_up": ("Coming up", "Demnächst"), "click_stock": ("Click a stock to see why it is owned.",
                                                             "Klicken Sie auf eine Aktie, um zu sehen, warum wir sie besitzen."),
    "checked_daily": ("Checked every weekday by two news analysts; a sale needs 2 of 3 reviewers plus a falling price.",
                      "Werktags von zwei Nachrichten-Analysten geprüft; ein Verkauf braucht 2 von 3 Prüfern und einen fallenden Kurs."),
    "basket_intro": ("Who is in, in what order and why — plus who is knocking on the door and who is closest to dropping out. Chosen every Sunday at 20:00.",
                     "Wer drin ist, in welcher Reihenfolge und warum – dazu, wer anklopft und wer am ehesten herausfällt. Jeden Sonntag um 20:00 gewählt."),
    "in_basket": ("In the basket", "Im Korb"), "rank": ("Rank", "Rang"), "sector_theme": ("Sector · theme", "Branche · Thema"),
    "score": ("Score", "Punkte"), "target_share": ("Target share", "Ziel-Anteil"), "note": ("Note", "Hinweis"),
    "score_note": ("Score = 12-month trend, scaled. The strongest gets 3× the money of the weakest.",
                   "Punkte = 12-Monats-Trend, skaliert. Die Stärkste bekommt 3× so viel Geld wie die Schwächste."),
    "knocking": ("Knocking on the door", "Klopfen an die Tür"),
    "knocking_note": ("Strong trends that did not make it in — and what keeps them out.",
                      "Starke Trends, die es nicht hineingeschafft haben – und was sie draußen hält."),
    "dropping": ("Closest to dropping out", "Am ehesten draußen"),
    "dropping_note": ("Inside the 6-month tax hold a stock only leaves if a sell rule fires. After 6 months it leaves when its rank falls below 24.",
                      "In der 6-Monats-Haltefrist geht eine Aktie nur, wenn eine Verkaufsregel greift. Danach, wenn ihr Rang unter 24 fällt."),
    "blk_red": ("Red flag from the AI review", "Warnsignal aus der KI-Prüfung"),
    "blk_unc": ("AI models disagree", "KI-Modelle uneinig"), "blk_theme": ("Theme limit (2 per theme)", "Themen-Grenze (2 je Thema)"),
    "blk_sector": ("Sector limit (5 per sector)", "Branchen-Grenze (5 je Branche)"), "blk_rank": ("Rank just below the cut", "Rang knapp unter der Grenze"),
    "need_sheet": ("This page needs the Google Sheet connection (set GOOGLE_SA_JSON and DASH_SHEET_ID on Render).",
                   "Diese Seite braucht die Verbindung zur Google-Tabelle (GOOGLE_SA_JSON und DASH_SHEET_ID auf Render setzen)."),
    "sheet_error": ("The Google Sheet could not be read right now.", "Die Google-Tabelle konnte gerade nicht gelesen werden."),
    "basket_of": ("Basket of", "Korb vom"),
    "health": ("Portfolio health", "Depot-Gesundheit"), "health_intro": ("How spread out the money is, and what could hurt it. Updated every Sunday.",
                                                                       "Wie breit das Geld gestreut ist und was ihm schaden könnte. Jeden Sonntag aktualisiert."),
    "checks_green": ("{a} of {b} checks green", "{a} von {b} Prüfungen grün"),
    "by_sector": ("By sector", "Nach Branche"), "by_theme": ("By theme", "Nach Thema"),
    "sector_rule": ("Rule: at most 5 of the 20 stocks per sector.", "Regel: höchstens 5 der 20 Aktien je Branche."),
    "theme_rule": ("Stocks that rise and fall together. Rule: at most 2 per theme from new picks.",
                   "Aktien, die gemeinsam steigen und fallen. Regel: höchstens 2 je Thema bei neuen Käufen."),
    "whatif": ("What if…? Crash scenarios", "Was wäre wenn…? Crash-Szenarien"),
    "whatif_note": ("Estimated loss of the basket compared with the S&P 500, from how each stock moved with oil, chips, interest rates and the market over the last year. Rule: at most 1.5× the S&P 500's loss. Real crashes are usually worse than estimates.",
                    "Geschätzter Verlust des Korbs im Vergleich zum S&P 500, berechnet aus dem Verhalten jeder Aktie gegenüber Öl, Chips, Zinsen und Markt im letzten Jahr. Regel: höchstens das 1,5-Fache des S&P-Verlusts. Echte Crashs sind meist schlimmer als Schätzungen."),
    "limit": ("Limit", "Grenze"), "within": ("Within limit", "Innerhalb"), "near": ("Near limit", "Nahe Grenze"),
    "over": ("Over limit", "Über Grenze"), "hit_hardest": ("Hit hardest", "Am stärksten betroffen"),
    "news_watch": ("News risk watch", "Nachrichten-Risiko"),
    "news_watch_note": ("An AI risk analyst reads the week's headlines. Headlines alone can only raise a warning; the basket is only made safer when prices confirm it.",
                        "Ein KI-Risikoanalyst liest die Schlagzeilen der Woche. Schlagzeilen allein lösen nur eine Warnung aus; der Korb wird erst sicherer gemacht, wenn die Kurse es bestätigen."),
    "rk_prices": ("What prices say", "Was die Kurse sagen"),
    "rk_news": ("What the headlines say", "Was die Schlagzeilen sagen"),
    "full_research": ("Full research", "Ganze Recherche"),
    "back_basket": ("← Back to the basket", "← Zurück zum Korb"),
    "st_in": ("In the basket · rank {r}", "Im Korb · Rang {r}"),
    "st_out": ("Not in the basket (contender · rank {r})", "Nicht im Korb (Anwärter · Rang {r})"),
    "st_none": ("Not in the basket", "Nicht im Korb"),
    "why_here": ("Why it is in the basket", "Warum sie im Korb ist"),
    "why_not": ("Why it is not in yet", "Warum sie noch nicht dabei ist"),
    "week_decision": ("This week's decision", "Entscheidung dieser Woche"),
    "key_facts": ("Key facts", "Eckdaten"),
    "f_rank": ("Rank (of the S&P 500 ranking)", "Rang (S&P-500-Rangliste)"),
    "f_score": ("Quality score", "Qualitäts-Score"),
    "f_weight": ("Target share of the basket", "Soll-Anteil am Korb"),
    "f_target": ("Analyst target price", "Kursziel der Analysten"),
    "f_conv": ("Conviction", "Überzeugung"),
    "f_added": ("In the watch list since", "Auf der Liste seit"),
    "f_next": ("Next results", "Nächste Zahlen"),
    "f_r3": ("Price change, 3 months", "Kursänderung, 3 Monate"),
    "f_r6": ("Price change, 6 months", "Kursänderung, 6 Monate"),
    "f_dd": ("Below its 52-week high", "Unter dem 52-Wochen-Hoch"),
    "f_rsi": ("RSI (14 days)", "RSI (14 Tage)"),
    "f_risk": ("Main risk exposure", "Wichtigstes Risiko"),
    "own_it": ("We own it", "Wir besitzen sie"),
    "own_since": ("since {d} · now {v} · {g}", "seit {d} · jetzt {v} · {g}"),
    "see_holding": ("Open in Holdings", "In „Bestand“ öffnen"),
    "researched_on": ("Researched on", "Recherchiert am"),
    "sources": ("Sources", "Quellen"),
    "no_research": ("There is no research on this stock yet. It is not in the basket and not among the contenders.",
                    "Zu dieser Aktie gibt es noch keine Recherche. Sie ist weder im Korb noch unter den Anwärtern."),
    "hold_title": ("What we hold today", "Was wir heute besitzen"),
    "hold_note": ("The same crash scenarios, run on the real positions with their real sizes. Money not yet invested counts as 0%, so while the basket is still being built the loss is smaller than the basket's. Information only: nothing is sold automatically because of it.",
                  "Dieselben Krisen-Szenarien, gerechnet mit den echten Positionen und ihren echten Größen. Noch nicht investiertes Geld zählt als 0 %, solange der Korb noch aufgebaut wird, ist der Verlust deshalb kleiner als beim Korb. Nur zur Information: deshalb wird nichts automatisch verkauft."),
    "hold_empty": ("Nothing bought yet: a bar for what we actually hold appears here by itself after the first purchases.",
                   "Noch nichts gekauft: ein Balken für unseren echten Bestand erscheint hier nach den ersten Käufen von selbst."),
    "hold_meta": ("Blue bar = what we actually hold today: {n} stocks · {inv} invested · {cash} cash (cash counts as 0%). Information only.", "Blauer Balken = was wir heute wirklich besitzen: {n} Aktien · {inv} investiert · {cash} Bargeld (Bargeld zählt als 0 %). Nur zur Information."),
    "hold_err": ("The check on the real positions could not be calculated right now.",
                 "Die Prüfung der echten Positionen konnte gerade nicht berechnet werden."),
    "your_holdings": ("What we hold", "Unser Bestand"),
    "severe_label": ("AI bubble bursts (severe)", "KI-Blase platzt (schwer)"),
    "corr_basket": ("The weekly basket (target)", "Der Wochenkorb (Ziel)"),
    "corr_hold": ("What we hold today", "Was wir heute besitzen"),
    "corr_hold_none": ("Needs at least two stocks held. Fills in after the first purchases.", "Braucht mindestens zwei gehaltene Aktien. Füllt sich nach den ersten Käufen."),
    "mon_1": ("Jan", "Jan"),
    "mon_2": ("Feb", "Feb"),
    "mon_3": ("Mar", "Mär"),
    "mon_4": ("Apr", "Apr"),
    "mon_5": ("May", "Mai"),
    "mon_6": ("Jun", "Jun"),
    "mon_7": ("Jul", "Jul"),
    "mon_8": ("Aug", "Aug"),
    "mon_9": ("Sep", "Sep"),
    "mon_10": ("Oct", "Okt"),
    "mon_11": ("Nov", "Nov"),
    "mon_12": ("Dec", "Dez"),
    "px_tip_stock": ("Price", "Kurs"), "px_tip_spy": ("S&P 500 equivalent", "S&P-500-Gegenwert"),
    "px_today": ("on the day", "am Tag"),
    "px_asof": ("last close {d}", "letzter Schlusskurs {d}"),
    "px_title": ("The last year", "Das letzte Jahr"),
    "px_bought": ("we bought here", "hier gekauft"),
    "px_none": ("The price history could not be loaded right now.", "Der Kursverlauf konnte gerade nicht geladen werden."),
    "px_facts": ("Price in dollars (dividend-adjusted). The grey line is the S&P 500, scaled to start at the same price, so you see what the same money would have done there. Today the price stands {hi} against its one-year high and {lo} against its one-year low. Move the mouse over the chart (or drag a finger) to see the price on any day.",
                 "Kurs in Dollar (um Dividenden bereinigt). Die graue Linie ist der S&P 500, auf denselben Startkurs skaliert: So sehen Sie, was dasselbe Geld dort gemacht hätte. Heute steht der Kurs {hi} gegenüber dem Jahreshoch und {lo} gegenüber dem Jahrestief. Maus über die Grafik bewegen (oder mit dem Finger ziehen), um den Kurs an jedem Tag zu sehen."),
    "by_corr": ("How they move together", "Wie sie sich gemeinsam bewegen"),
    "corr_rule": ("Correlation: 1.0 = two stocks move the same way every day, 0 = unrelated. Measured on daily moves over about a year.", "Korrelation: 1,0 = zwei Aktien bewegen sich jeden Tag gleich, 0 = unabhängig. Gemessen an Tagesbewegungen über etwa ein Jahr."),
    "corr_avg": ("average between all pairs", "Durchschnitt über alle Paare"),
    "corr_well": ("Well spread", "Gut gestreut"), "corr_mod": ("Moderate", "Mäßig"), "corr_one": ("Mostly one bet", "Fast eine einzige Wette"),
    "corr_eff": ("independent bets, from {n} stocks. Fewer than the stock count means they overlap.", "unabhängige Wetten aus {n} Aktien. Weniger als die Aktienzahl heißt: sie überlappen."),
    "corr_groups": ("Move together (0.70 or more)", "Bewegen sich gemeinsam (0,70 oder mehr)"),
    "corr_nogroup": ("No group of stocks moves that closely together.", "Keine Aktiengruppe bewegt sich so eng zusammen."),
    "corr_pairs": ("Most similar pairs", "Ähnlichste Paare"),
    "corr_err": ("Could not be calculated right now.", "Konnte gerade nicht berechnet werden."),
    "corr_note": ("Information only, no limit. In a crash, correlations rise toward 1, so this flatters calm times. The crash scenarios below remain the main safety check.", "Nur zur Information, keine Grenze. In einem Crash steigen die Korrelationen Richtung 1, die Zahl schmeichelt also ruhigen Zeiten. Die Crash-Szenarien unten bleiben die wichtigste Sicherheitsprüfung."),
    "shadow_title": ("What if we held less AI? (paper simulation)", "Was wäre bei weniger KI? (Simulation)"),
    "shadow_intro": ("Two pretend portfolios, same money, same dates, same simple rules. One follows our weekly basket. The other swaps the most AI-sensitive stocks for the best-ranked stocks that hardly react to chip stocks. Only the AI exposure differs.",
                     "Zwei Spiel-Portfolios, gleiches Geld, gleiche Daten, gleiche einfache Regeln. Eines folgt unserem Wochenkorb. Das andere tauscht die KI-empfindlichsten Aktien gegen die bestplatzierten Aktien, die kaum auf Chip-Aktien reagieren. Nur das KI-Risiko ist anders."),
    "shadow_cur": ("Current basket", "Aktueller Korb"),
    "shadow_low": ("Low-AI basket", "KI-armer Korb"),
    "shadow_wait": ("Not enough history yet. This fills in as weekly runs and trading days add up.", "Noch zu wenig Verlauf. Das füllt sich mit den wöchentlichen Läufen und Handelstagen."),
    "shadow_err": ("The simulation could not be calculated right now.", "Die Simulation konnte gerade nicht berechnet werden."),
    "shadow_exposure": ("AI sensitivity (1.0 = moves like the chip sector relative to the market): current basket {a}, Low-AI basket {b}.",
                        "KI-Empfindlichkeit (1,0 = bewegt sich wie der Chip-Sektor relativ zum Markt): aktueller Korb {a}, KI-armer Korb {b}."),
    "shadow_dropped": ("dropped, no suitable replacement", "gestrichen, kein passender Ersatz"),
    "shadow_noswap": ("This week no stock is above the AI limit, so both baskets are the same.", "Diese Woche liegt keine Aktie über der KI-Grenze, beide Körbe sind gleich."),
    "shadow_note": ("Both lines use the same simplified rules: weekly rebalance, no daily trend exits, no three-step build-up, no costs, deposits invested at the next weekly run. So they differ from the real account on purpose. Only the gap between them is meaningful, and only after many weeks.",
                    "Beide Linien nutzen dieselben vereinfachten Regeln: wöchentliche Anpassung, keine täglichen Trend-Ausstiege, kein dreistufiger Aufbau, keine Kosten, Einzahlungen werden beim nächsten Wochenlauf investiert. Sie weichen daher bewusst vom echten Konto ab. Aussagekräftig ist nur der Abstand zwischen beiden, und erst nach vielen Wochen."),
    "info_only": ("Information only", "Nur zur Information"),
    "severe_note": ("Severe case: the S&P 500 falls 25% and chip stocks about 55% (the dot-com bust of 2000–02 was worse). This row never triggers a swap. Note: a momentum basket is heavy in AI-linked stocks, so we may need a ceiling on AI exposure. To be decided after a few weeks of real runs.",
                    "Schwerer Fall: Der S&P 500 fällt um 25 %, Chip-Aktien um etwa 55 % (das Platzen der Dotcom-Blase 2000–02 war schlimmer). Diese Zeile löst nie einen Tausch aus. Hinweis: Ein Momentum-Korb enthält viele KI-nahe Aktien, deshalb brauchen wir vielleicht eine Obergrenze für das KI-Risiko. Das entscheiden wir nach einigen Wochen echter Läufe."),
    "act_if": ("Would act if", "Würde handeln, wenn"),
    "chk_spread": ("Spread out", "Breit gestreut"), "chk_limits": ("Crash limits held", "Crash-Grenzen eingehalten"),
    "chk_beta": ("Market sensitivity", "Schwankung gegenüber Markt"), "chk_theme": ("Theme concentration", "Themen-Konzentration"),
    "activity_intro": ("Every decision the bot made, and why — including the times it chose to wait.",
                       "Jede Entscheidung des Bots und warum – auch, wenn er bewusst gewartet hat."),
    "all": ("All", "Alle"), "buys": ("Buys", "Käufe"), "sells": ("Sells", "Verkäufe"), "waits": ("Waits", "Warten"),
    "checks": ("Checks", "Prüfungen"), "test_run": ("test run", "Probelauf"), "rule": ("Rule", "Regel"),
    "no_activity": ("No runs recorded yet.", "Noch keine Läufe aufgezeichnet."),
    "downloads": ("Downloads: check everything yourself", "Downloads: alles selbst prüfen"),
    "downloads_note": ("The raw records behind this site. Anyone with a login can download them — for example to ask an adviser or another AI for a second opinion. Passwords and keys are never included.",
                       "Die Rohdaten hinter dieser Seite. Jeder mit Zugang kann sie herunterladen – etwa für eine zweite Meinung von einem Berater oder einer anderen KI. Passwörter und Schlüssel sind nie enthalten."),
    "dl_run": ("Latest run (JSON)", "Letzter Lauf (JSON)"),
    "dl_run_t": ("The latest daily run (planned and placed orders, waits, deep-dive decisions) and the latest weekly basket run (ranking, risk scenarios, AI risk view).",
                 "Der letzte Tageslauf (geplante und ausgeführte Orders, Wartefälle, Entscheidungen der Tiefenprüfung) und der letzte wöchentliche Korb-Lauf (Rangliste, Risiko-Szenarien, KI-Risikoeinschätzung)."),
    "dl_trades": ("All buys and sells (CSV, opens in Excel)", "Alle Käufe und Verkäufe (CSV, öffnet in Excel)"),
    "dl_trades_t": ("Every order with date, amount and the rule behind it, updated after each daily run.",
                    "Jede Order mit Datum, Betrag und der Regel dahinter, nach jedem Tageslauf aktualisiert."),
    "dl_audit": ("Audit log (CSV)", "Prüfprotokoll (CSV)"),
    "dl_audit_t": ("Every change to the bot's code: date, change number and what changed. Nothing changes without an entry here.",
                   "Jede Änderung am Programm: Datum, Änderungsnummer und was geändert wurde. Nichts ändert sich ohne Eintrag hier."),
    "dl_bt": ("Backtest reports (text)", "Backtest-Berichte (Text)"),
    "dl_bt_t": ("The test rounds on past data, with method, results and limitations (English).",
                "Die Testrunden mit historischen Daten, mit Methode, Ergebnissen und Einschränkungen (Englisch)."),
    "download": ("Download", "Herunterladen"),
    "weekly_report": ("Weekly report", "Wochenbericht"),
    "weekly_soon": ("Written weekly reports are coming next. Until then, Activity shows every decision.",
                    "Schriftliche Wochenberichte kommen als Nächstes. Bis dahin zeigt Aktivität jede Entscheidung."),
    "system": ("System status (owner only)", "Systemstatus (nur Inhaber)"),
    "last_daily": ("Last daily run", "Letzter Tageslauf"), "last_weekly": ("Last weekly run", "Letzter Wochenlauf"),
    "research_desk": ("Research notes updated", "Recherche aktualisiert"), "sheet": ("Google Sheet", "Google-Tabelle"),
    "connected": ("connected", "verbunden"), "not_connected": ("not connected", "nicht verbunden"),
    "errors": ("Errors", "Fehler"), "none": ("none", "keine"),
    "profile_intro": ("Saved in this browser.", "In diesem Browser gespeichert."),
    "greet_as": ("How should we greet you?", "Wie sollen wir Sie begrüßen?"),
    "greet_eg": ("For example “Mama”, “Papa” or your first name.", "Zum Beispiel „Mama“, „Papa“ oder Ihr Vorname."),
    "language": ("Language", "Sprache"), "text_size": ("Text size", "Schriftgröße"), "normal": ("Normal", "Normal"),
    "large": ("Large", "Groß"), "save": ("Save", "Speichern"), "saved": ("Saved.", "Gespeichert."),
    "pw_note": ("To change your password, ask Tim.", "Um das Passwort zu ändern, bitte Tim fragen."),
    "view_note": ("Your access is view-only: you see every number and reason, but cannot buy or sell anything.",
                  "Ihr Zugang ist zum Ansehen: Sie sehen alle Zahlen und Begründungen, können aber nichts kaufen oder verkaufen."),
    "data_issue": ("Some data could not be loaded right now", "Einige Daten konnten gerade nicht geladen werden"),
    "example_none": ("—", "—"),
}

TAGS = {"BUY": ("BUY", "KAUF"), "SELL": ("SELL", "VERKAUF"), "WAIT": ("WAIT", "WARTEN"), "CHECK": ("CHECK", "PRÜFUNG"),
        "ALARM": ("ALARM", "ALARM")}

MONTHS_DE = ["Jan.", "Feb.", "März", "Apr.", "Mai", "Juni", "Juli", "Aug.", "Sep.", "Okt.", "Nov.", "Dez."]
MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def t(key, lang, **kw):
    if key.startswith(("need_sheet:", "sheet_error:")):
        base, _, detail = key.partition(":")
        return t(base, lang) + (f" [{detail}]" if detail else "")
    v = T.get(key, (key, key))[1 if lang == "de" else 0]
    return v.format(**kw) if kw else v


def _num(v, dec, lang):
    s = f"{abs(v):,.{dec}f}"
    if lang == "de":
        s = s.replace(",", "§").replace(".", ",").replace("§", ".")
    return s


def money(v, lang, dec=2, sign=False):
    if v is None:
        return "—"
    s = _num(v, dec, lang)
    pre = "−" if v < 0 else ("+" if sign and v > 0 else "")
    return f"{pre}{s} $" if lang == "de" else f"{pre}${s}"


def pct(v, lang, dec=1, sign=True):
    """v in percent units (5.3 -> '+5.3%')."""
    if v is None:
        return "—"
    pre = "−" if v < 0 else ("+" if sign and v > 0 else "")
    return f"{pre}{_num(v, dec, lang)} %" if lang == "de" else f"{pre}{_num(v, dec, lang)}%"


def date(iso, lang):
    if not iso or len(str(iso)) < 10:
        return iso or "—"
    try:
        y, m, d = int(iso[:4]), int(iso[5:7]), int(iso[8:10])
    except ValueError:
        return iso
    return f"{d}. {MONTHS_DE[m - 1]} {y}" if lang == "de" else f"{d} {MONTHS_EN[m - 1]} {y}"


def explain_order(o, lang):
    """(tag, plain title) for an order or skipped buy from /rebalance's orders_json."""
    de = lang == "de"
    kind, reason, status = o.get("kind", ""), str(o.get("reason", "")), o.get("status", "")
    sym = o.get("symbol", "")
    if status == "skipped":
        r = reason.lower()
        if "earnings" in r or "deep dive (timing)" in r:
            return "WAIT", (f"{sym}: gewartet – Nachrichten oder Quartalszahlen stehen an" if de
                            else f"{sym}: waited — news or earnings due")
        m = re.search(r"up (\d+)% in 5 days", r)
        if m:
            return "WAIT", (f"{sym}: gewartet – Kurssprung +{m.group(1)} % in 5 Tagen" if de
                            else f"{sym}: waited — jumped {m.group(1)}% in 5 days")
        m = re.search(r"down (\d+)% in one day", r)
        if m:
            return "WAIT", (f"{sym}: gewartet – heute −{m.group(1)} %" if de else f"{sym}: waited — fell {m.group(1)}% today")
        m = re.search(r"down (\d+)% in 10 days", r)
        if m:
            return "WAIT", (f"{sym}: gewartet – Kurssturz −{m.group(1)} % in 10 Tagen" if de
                            else f"{sym}: waited — fell {m.group(1)}% in 10 days")
        if "buy-back" in r:
            return "WAIT", (f"{sym}: wartet auf das Rückkauf-Signal" if de else f"{sym}: waiting for the buy-back signal")
        if "thesis" in r:
            return "WAIT", (f"{sym}: kein Kauf – Geschichte gebrochen" if de else f"{sym}: not bought — story broken")
        return "WAIT", (f"{sym}: gewartet" if de else f"{sym}: waited")
    if o.get("side") == "sell":
        title = {"drop": ("nicht mehr im Korb", "no longer in the basket"),
                 "trend": ("Trend gebrochen", "trend broken"),
                 "stop": ("Notbremse (−35 %)", "emergency stop (−35%)"),
                 "exit": ("Geschichte gebrochen (Tiefenprüfung)", "story broken (deep dive)"),
                 "trim": ("über Zielgröße reduziert", "trimmed above its target")}.get(kind, ("verkauft", "sold"))
        return "SELL", (f"{sym} verkauft: {title[0]}" if de else f"Sold {sym}: {title[1]}")
    m = re.search(r"tranche (\d)/(\d)", reason)
    if m:
        return "BUY", (f"{sym} gekauft: Teil {m.group(1)} von {m.group(2)}" if de
                       else f"Bought {sym}: part {m.group(1)} of {m.group(2)}")
    if kind == "deploy":
        return "BUY", (f"{sym}: neues Geld angelegt" if de else f"{sym}: new money invested")
    if kind == "drift":
        return "BUY", (f"{sym} auf Zielgröße aufgestockt" if de else f"{sym} topped up to its target")
    return "BUY", (f"{sym} gekauft" if de else f"Bought {sym}")


def explain_decision(d, lang):
    de = lang == "de"
    sym, action = d.get("symbol", ""), d.get("action", "")
    txt = {"exit": ("Tiefenprüfung: Geschichte gebrochen – verkaufen", "Deep dive: story broken — sell"),
           "hold": ("Tiefenprüfung: unsicher – vorerst nicht nachkaufen", "Deep dive: unclear — no new buying for now"),
           "wait": ("Tiefenprüfung: Kauf verschoben", "Deep dive: buy delayed"),
           "none": ("Tiefenprüfung: Fehlalarm – nichts zu tun", "Deep dive: false alarm — nothing to do")}.get(
        action, ("Tiefenprüfung", "Deep dive"))
    return ("SELL" if action == "exit" else "CHECK"), f"{sym}: {txt[0] if de else txt[1]}"


# --------------------------------------------------------------------------- news risk watch (plain words)
# The weekly risk analyst writes in data-field shorthand ("USO ret_1m_pct -2.0"). These helpers turn that
# into sentences a family member can read. Pure text clean-up: nothing is added that the analyst did not say.

_RISK_NAMES = {"oil": ("Oil", "Öl"), "ai": ("AI & chip stocks", "KI & Chip-Aktien"),
               "rates": ("Interest rates", "Zinsen"), "market": ("Overall market", "Gesamtmarkt"),
               "politics": ("Politics & geopolitics", "Politik & Geopolitik"),
               "geopolitics": ("Politics & geopolitics", "Politik & Geopolitik")}
_RISK_LEVELS = {"low": ("Low", "Niedrig"), "elevated": ("Elevated", "Erhöht"), "high": ("High", "Hoch"),
                "moderate": ("Moderate", "Mäßig"), "medium": ("Moderate", "Mäßig")}
_FUNDS = {"USO": ("oil fund", "Öl-Fonds"), "SMH": ("chip-stock fund", "Chip-Aktien-Fonds"),
          "TLT": ("long-term bond fund", "Staatsanleihen-Fonds"), "SPY": ("S&P 500 fund", "S&P-500-Fonds"),
          "MTUM": ("momentum fund", "Momentum-Fonds"), "QQQ": ("Nasdaq fund", "Nasdaq-Fonds"),
          "GLD": ("gold fund", "Gold-Fonds"), "XLE": ("energy-stock fund", "Energie-Fonds")}
_SPAN = {"1w": ("1-week move", "1-Wochen-Bewegung"), "1m": ("1-month move", "1-Monats-Bewegung"),
         "3m": ("3-month move", "3-Monats-Bewegung")}
_NUMRE = r"([+\-−]?\d+(?:\.\d+)?)"


def risk_name(key, lang):
    k = (key or "").strip().lower()
    return _RISK_NAMES.get(k, (k.replace("_", " ").title(),) * 2)[1 if lang == "de" else 0]


def risk_level(key, lang):
    k = (key or "").strip().lower()
    return _RISK_LEVELS.get(k, (k.title(),) * 2)[1 if lang == "de" else 0]


def _sgn(s):
    return s.replace("−", "-")


def plain_risk(text, lang="en", trigger=False):
    """Replace data-field shorthand with words; add % signs; label the index funds once."""
    if not text:
        return ""
    de = 1 if lang == "de" else 0
    s = str(text)
    s = re.sub(r"ret_(1w|1m|3m)_pct\s*" + _NUMRE,
               lambda m: f"{_SPAN[m.group(1)][de]} {_sgn(m.group(2))}%", s)
    s = re.sub(r"from_1y_high_pct\s*" + _NUMRE,
               lambda m: ("at its 1-year high" if not de else "auf dem 1-Jahres-Hoch") if float(_sgn(m.group(1))) == 0
               else (f"{abs(float(_sgn(m.group(1)))):g}% below its 1-year high" if not de
                     else f"{abs(float(_sgn(m.group(1)))):g}% unter dem 1-Jahres-Hoch"), s)
    s = re.sub(r"vol_1m(?:_pct)?\s*" + _NUMRE,
               lambda m: ("1-month volatility " if not de else "1-Monats-Schwankung ") + f"{m.group(1)}%", s)
    s = re.sub(r"vol_1y(?:_pct)?\s*" + _NUMRE,
               lambda m: ("1-year volatility " if not de else "1-Jahres-Schwankung ") + f"{m.group(1)}%", s)
    s = re.sub(r"ret_(1w|1m|3m)_pct", lambda m: _SPAN[m.group(1)][de], s)
    s = s.replace("from_1y_high_pct", "distance from its 1-year high" if not de else "Abstand zum 1-Jahres-Hoch")
    s = s.replace("vol_1m_pct", "1-month volatility" if not de else "1-Monats-Schwankung")
    s = s.replace("vol_1m", "1-month volatility" if not de else "1-Monats-Schwankung")
    s = s.replace("vol_1y", "1-year volatility" if not de else "1-Jahres-Schwankung")
    if trigger:
        s = re.sub(r"\b(above|below)\s*" + _NUMRE + r"(?![\d%.])",
                   lambda m: f"{m.group(1)} {_sgn(m.group(2))}%", s)
        if de:
            s = re.sub(r"\babove\b", "über", re.sub(r"\bbelow\b", "unter", s)).replace(" or ", " oder ")
    for sym, lab in _FUNDS.items():
        s = re.sub(rf"\b{sym}\b", f"{sym} ({lab[de]})", s, count=1)
    s = s.replace(" (at the high)", "")
    if de:
        s = re.sub(r"(\d)\.(\d)", r"\1,\2", s)
    s = re.sub(r"\b(20\d\d)-(\d\d)-(\d\d)\b", lambda m: date(f"{m.group(1)}-{m.group(2)}-{m.group(3)}", lang), s)
    return re.sub(r"\s+", " ", s).strip()


def split_risk(text):
    """-> (prices, headlines, bottom line): the analyst usually writes 'prices... Headlines on <date>: ... <verdict>.'"""
    t_ = re.sub(r"\s+", " ", str(text or "")).strip()
    if not t_:
        return "", "", ""
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", t_)
    prices, news = [], []
    seen_news = False
    for p in parts:
        if re.match(r"Headlines? (on|for|from)\b", p) or re.match(r"(Offsetting|Mixed|Several|The headlines)\b", p):
            seen_news = True
        (news if seen_news else prices).append(p)
    bottom = ""
    if news and len(news) > 1:
        bottom = news.pop()
    elif not news and len(prices) > 1:
        bottom = prices.pop()
    return " ".join(prices), " ".join(news), bottom
