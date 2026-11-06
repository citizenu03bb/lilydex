"""Explicit accepted prices for existing reservation scenarios on temporary stores."""


def accepted_prices(store, listing_ids):
    with store.connect() as db:
        return {listing_id: (row[0] if (row := db.execute(
            "SELECT price_cents FROM listings WHERE id=?", (listing_id,)
        ).fetchone()) else 0) for listing_id in listing_ids}
