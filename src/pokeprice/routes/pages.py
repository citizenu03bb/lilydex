"""The web application's page renderer and the pages it builds, once per application.

``page`` fills an HTML file of ``web/`` with the dictionary of its language, the
site's name and, for public pages, the search-engine metadata; ``about_page`` and
``conditions_page`` add the seller's contact, payment methods and shipping rates.
The builders keep the local ``words = dictionaries[language]`` idiom that
``tests/test_messages.py`` reads to find the keys the server uses.
"""

import html
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..brand import SITE_NAME, site_wordmark
from ..notifications import Notifier, euros
from ..reservations import SHIPPING_SERVICES, Reservations, shipping_config
from ..web_constants import LANGUAGES, NOINDEX, TEXT_KEY


@dataclass(frozen=True)
class Pages:
    """The interface texts and the page builders the routes share."""

    static: Path
    dictionaries: dict[str, dict[str, Any]]
    page: Callable[..., str]
    about_page: Callable[..., str]
    conditions_page: Callable[..., str]


def build_pages(public_origin: str, indexing: bool, reservations: Reservations, notifier: Notifier) -> Pages:
    static = Path(__file__).parent.with_name("web")

    small, large = site_wordmark()
    wordmark = (f"<span>{html.escape(small)}</span>" if small else "") + f"<em>{html.escape(large)}</em>"

    # The interface texts, one dictionary per language (docs/decisions/0020).
    dictionaries = {
        code: json.loads(static.joinpath("messages", f"{code}.json").read_text())
        for code in LANGUAGES
    }

    def listing_summary(language, listing):
        """What a fiche says about itself: its name, price, description and photo."""
        words = dictionaries[language]
        first = listing["items"][0]
        name = listing["title"] or first["name"]
        price = f"{listing['price_cents'] / 100:,.2f}"
        price = price.replace(",", "\u202f").replace(".", ",") + "\u00a0€" if language == "fr" else "€" + price
        condition = (words["item.condition"].format(condition=first["condition"])
                     if first["condition"] else words["item.condition_unconfirmed"])
        fields = {
            "name": first["name"], "title": name, "extension": first["set_name"],
            "number": first["number"], "price": price,
            "count": sum(not item.get("offered") for item in listing["items"]),
            "condition": condition,
        }
        template = words["share.lot_description"] if len(listing["items"]) > 1 else words["share.card_description"]
        gifts = sum(bool(item.get("offered")) for item in listing["items"])
        if gifts:
            # The offered Energies are a gift, told apart from the lot's cards (0041).
            template += " " + words["share.offered"].replace("{count}", str(gifts))
        image = None
        photo = first.get("media", {}).get("front")
        if photo:
            variants = [v for v in photo["variants"] if v["format"] == "jpeg"]
            # A public consultation derivative, never the private capture original.
            if variants:
                image = max(variants, key=lambda v: v["width"] * v["height"])
        return {"first": first, "name": name, "price": price, "condition": condition,
                "description": template.format(**fields), "image": image,
                "alt": words.get("share.image_alt", "{name}").format(name=first["name"])}

    def card_summary(language, listing):
        """The fiche in plain HTML, for robots and readers without JavaScript.

        storefront.js removes it once the fiche opens in its dialog.
        """
        words = dictionaries[language]
        summary = listing_summary(language, listing)
        first, esc = summary["first"], html.escape
        parts = ['<article id="card-summary" class="card-summary" aria-labelledby="card-summary-title">']
        if image := summary["image"]:
            parts.append(f'<img src="{esc(image["url"], quote=True)}" alt="{esc(summary["alt"], quote=True)}"'
                         f' width="{int(image["width"])}" height="{int(image["height"])}" />')
        parts.append("<div>")
        parts.append(f'<h2 id="card-summary-title">{esc(summary["name"])}</h2>')
        if len(listing["items"]) > 1:
            parts.append(f"<p>{esc(summary['description'])}</p>")
            parts.append("<ul>" + "".join(
                f"<li>{esc(' · '.join(str(v) for v in (item['name'], item['set_name'], item['number']) if v))}</li>"
                for item in listing["items"] if not item.get("offered")) + "</ul>")
        else:
            details = " · ".join(str(v) for v in (first["set_name"], first["number"]) if v)
            parts.append(f"<p>{esc(details)}</p>")
            parts.append(f"<p>{esc(summary['condition'])}</p>")
            parts.append(f'<p class="card-summary-price">{esc(summary["price"])}</p>')
        parts.append("</div></article>")
        return "".join(parts)

    def public_head(language, rest, listing=None):
        words = dictionaries[language]
        generic_title = f"{SITE_NAME} · {words['meta.title']}"
        title = generic_title
        description = words.get("meta.description", words["hero.intro"])
        image = None
        first = None
        if listing:
            summary = listing_summary(language, listing)
            first, image, description = summary["first"], summary["image"], summary["description"]
            title = f"{summary['name']} · {SITE_NAME}"

        def tag(key, value, *, property=False):
            attr = "property" if property else "name"
            return f'<meta {attr}="{key}" content="{html.escape(str(value), quote=True)}" />'

        has_image = bool(public_origin and image)
        tags = [tag("description", description),
                tag("og:type", "product" if listing else "website", property=True),
                tag("og:site_name", SITE_NAME, property=True), tag("og:title", title, property=True),
                tag("og:description", description, property=True),
                tag("twitter:card", "summary_large_image" if has_image else "summary"),
                tag("twitter:title", title), tag("twitter:description", description)]
        image_url = None
        if public_origin:
            tags.append(tag("og:url", public_origin + LANGUAGES[language][1] + rest, property=True))
            if image:
                image_url = public_origin + image["url"]
                alt = summary["alt"]
                tags.extend([
                    tag("og:image", image_url, property=True), tag("og:image:type", "image/jpeg", property=True),
                    tag("og:image:width", image["width"], property=True),
                    tag("og:image:height", image["height"], property=True),
                    tag("og:image:alt", alt, property=True), tag("twitter:image", image_url),
                    tag("twitter:image:alt", alt),
                ])
        if listing:
            tags.append(product_data(listing, title, description, image_url, language, rest))
        return generic_title, title, "\n    ".join(tags)

    def product_data(listing, title, description, image_url, language, rest):
        """The fiche as schema.org Product/Offer, in a JSON-LD data block."""
        offer = {
            "@type": "Offer",
            "price": f"{listing['price_cents'] / 100:.2f}",
            "priceCurrency": "EUR",
            "availability": "https://schema.org/InStock",
            "itemCondition": "https://schema.org/UsedCondition",
        }
        product = {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": title.rsplit(f" · {SITE_NAME}", 1)[0],
            "description": description,
            "category": "Pokémon trading card" if language == "en" else "Carte Pokémon",
            "offers": offer,
        }
        if public_origin:
            url = public_origin + LANGUAGES[language][1] + rest
            product["url"] = offer["url"] = url
            if image_url:
                product["image"] = image_url
        # A data block, not a script: the CSP (script-src 'self') does not run it.
        return (
            '<script type="application/ld+json">'
            + json.dumps(product, ensure_ascii=False).replace("<", "\\u003c")
            + "</script>"
        )

    def alternate_links(language, rest):
        """canonical and hreflang links for a public address, given after the home."""
        if not public_origin:
            return ""
        canonical = public_origin + LANGUAGES[language][1] + rest
        links = [f'<link rel="canonical" href="{html.escape(canonical, quote=True)}" />']
        links += [f'<link rel="alternate" hreflang="{code}" href="{html.escape(public_origin + LANGUAGES[code][1] + rest, quote=True)}" />'
                 for code in LANGUAGES]
        links.append(f'<link rel="alternate" hreflang="x-default" href="{html.escape(public_origin + "/" + rest, quote=True)}" />')
        return "\n    ".join(links)

    def page(name: str, language: str = "fr", rest: str = "", *, listing=None, public=None) -> str:
        """A page as served: its texts come from the dictionary, the site's name from `brand`.

        `rest` is the address after the language's home, so the link to the other
        language leads to the same card. `public` is that address for a page search
        engines may know (canonical, hreflang); None keeps it out of their index.
        """
        words = dictionaries[language]
        lang, home = LANGUAGES[language]
        other = words["footer.language.code"]

        def word(match: re.Match) -> str:
            # A key ending in _html is trusted markup from the dictionary; the rest is text.
            key = match.group(1)
            return words[key] if key.endswith("_html") else html.escape(words[key])

        # A data block, not a script: the CSP lets it through, and "<" cannot close it.
        block = (
            '<script id="messages" type="application/json">'
            + json.dumps(words, ensure_ascii=False).replace("<", "\\u003c")
            + "</script>"
        )
        rendered = (
            TEXT_KEY.sub(word, static.joinpath(name).read_text())
            .replace("{{lang}}", lang)
            .replace("{{home}}", home)
            .replace("{{other_home}}", LANGUAGES[other][1])
            .replace("{{other_page}}", html.escape(LANGUAGES[other][1] + rest))
            .replace("{{messages}}", block)
            .replace("{{site_name}}", html.escape(SITE_NAME))
            .replace("{{site_wordmark}}", wordmark)
        )
        # Without indexing, or on a page no engine should keep, the noindex stays.
        robots = "" if indexing and public is not None else r"\g<1>" + NOINDEX + "\n"
        rendered = re.sub(r"( *)\{\{robots\}\}\n", robots, rendered, count=1)
        if name == "storefront.html":
            rendered = re.sub(r"( *)\{\{card_summary\}\}\n", lambda match:
                              match[1] + card_summary(language, listing) + "\n" if listing else "", rendered, count=1)
            generic, title, metadata = public_head(language, rest if listing else "", listing)
            rendered = re.sub(r"<title>.*?</title>", lambda _: f"<title>{html.escape(title)}</title>", rendered, count=1)
            rendered = re.sub(r"(<html\b[^>]*)(>)", lambda match:
                              match[1] + f' data-page-title="{html.escape(generic, quote=True)}">', rendered, count=1)
            rendered = rendered.replace("</head>", metadata + "\n  </head>", 1)
        if public is not None and (links := alternate_links(language, public)):
            rendered = rendered.replace("</head>", "  " + links + "\n  </head>", 1)
        return rendered

    # The seller's contact comes from the server's environment, never from the
    # public repository.
    contact_email = os.environ.get("POKEPRICE_CONTACT_EMAIL", "").strip()
    if not re.fullmatch(r"[^@\s<>\"']+@[^@\s<>\"']+\.[a-z]{2,}", contact_email, re.I):
        contact_email = ""
    # The data controller, a private individual, is named by the server too.
    controller_name = os.environ.get("POKEPRICE_CONTROLLER_NAME", "").strip()[:120]

    def about_page(language):
        en = language == "en"
        contact = (
            f'<a href="mailto:{html.escape(contact_email)}">{html.escape(contact_email)}</a>'
            if contact_email
            else "The contact address will be given here soon." if en
            else "L’adresse de contact sera bientôt indiquée ici."
        )
        who = html.escape(controller_name) if controller_name else ""
        if en:
            controller = (
                f"Data controller: {who or 'the seller'}, as a private individual, "
                "reachable at the contact address below."
            )
        else:
            controller = (
                f"Responsable du traitement : {who or 'le vendeur'}, à titre "
                "personnel, joignable à l’adresse de contact ci-dessous."
            )
        payment = payment_sentence(
            en,
            ": the seller sends you the amount, the lot’s reference "
            "and their payment details by email; with an account, you also find "
            "them in “My requests” while the lot awaits payment."
            if en
            else " : le vendeur vous envoie le montant, la référence du lot "
            "et ses coordonnées par e-mail ; avec un compte, vous les retrouvez aussi "
            "dans « Mes demandes » tant que le lot attend son paiement.",
        )
        return (
            page("about.en.html" if en else "about.html", language, public="a-propos")
            .replace("{{contact}}", contact)
            .replace("{{controller}}", controller)
            .replace("{{payment}}", html.escape(payment))
        )

    def payment_sentence(en, detail):
        """The accepted payment methods, followed by what the seller sends."""
        if en:
            methods = reservations.payment_methods(
                {"wero": "Wero", "iban": "bank transfer", "paypal": "PayPal (goods and services)"}
            )
            start, last = "Payment by ", " or "
        else:
            methods = reservations.payment_methods()
            start, last = "Paiement par ", " ou "
        if not methods:
            return (
                "The seller tells you in their reply how to pay."
                if en
                else "Le vendeur vous indique dans sa réponse comment payer."
            )
        return (
            start + ", ".join(methods[:-1]) + (last if len(methods) > 1 else "")
            + methods[-1] + detail
        )

    def conditions_page(language):
        en = language == "en"
        contact = (
            f'<a href="mailto:{html.escape(contact_email)}">{html.escape(contact_email)}</a>'
            if contact_email
            else "The contact address will be given here soon." if en
            else "L’adresse de contact sera bientôt indiquée ici."
        )
        payment = payment_sentence(
            en,
            ": the seller sends you the total amount, the reservation reference "
            "and payment details by email."
            if en
            else " : le vendeur vous envoie le montant total, la référence du lot "
            "et ses coordonnées par e-mail.",
        )
        # The tables come from the rates the basket uses: one grid to update.
        rates = shipping_config(notifier)

        def price(cents):
            return f"{cents / 100:.2f} €" if en else euros(cents)

        def rows(tariffs):
            return "\n".join(
                f"<tr><td>{r['max_grams']:,} g</td>".replace(",", "," if en else "\u202f")
                + f"<td>{price(r['shipping_cents'])}</td><td>{SHIPPING_SERVICES[r['service']]}</td></tr>"
                for r in tariffs
            )

        return (
            page("conditions.en.html" if en else "conditions.html", language, rest="conditions", public="conditions")
            .replace("{{contact}}", contact)
            .replace("{{payment}}", html.escape(payment))
            .replace("{{threshold}}", price(rates["registered_threshold_cents"]).replace(" €", "\u00a0€"))
            .replace("{{packing_grams}}", str(rates["packing_grams"]))
            .replace("{{card_grams}}", str(rates["card_weight_grams"]))
            .replace("{{tracked_rows}}", rows(rates["tracked_tariffs"]))
            .replace("{{registered_rows}}", rows(rates["registered_tariffs"]))
        )

    return Pages(
        static=static,
        dictionaries=dictionaries,
        page=page,
        about_page=about_page,
        conditions_page=conditions_page,
    )
