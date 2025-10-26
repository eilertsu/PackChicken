"""
packchicken.utils.pdf

Hjelpefunksjoner for å generere Bring-lignende PDF-etiketter
eller pakksedler. Bruker reportlab for å generere A6 eller A4 PDF-er.
"""

from reportlab.lib.pagesizes import A6, A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from datetime import datetime


def generate_label_only(order: dict, tracking_number: str, outfile, size: str = "A6"):
    """
    Generer en enkel Bring-lignende fraktetikett.
    Args:
        order: dict med shipping info
        tracking_number: sporingsnummer fra Bring eller simulert
        outfile: filsti (Path eller str)
        size: "A6" eller "A4"
    """
    page_size = A6 if size.upper() == "A6" else A4
    c = canvas.Canvas(str(outfile), pagesize=page_size)
    width, height = page_size

    # Sikkerhet: hent ut shipping info med defaults
    ship = order.get("shipping_address", {})
    name = order.get("name", "Ukjent mottaker")
    addr1 = ship.get("address1", "")
    zip_ = ship.get("zip", "")
    city = ship.get("city", "")
    country = ship.get("country", "NO")
    phone = order.get("phone", "")

    # Overskrift
    c.setFont("Helvetica-Bold", 14)
    c.drawString(15 * mm, height - 20 * mm, "Bring Shipping Label")

    c.setFont("Helvetica", 10)
    c.drawString(15 * mm, height - 30 * mm, f"Tracking: {tracking_number}")
    c.drawString(15 * mm, height - 37 * mm, f"Order ID: {order.get('order_number', 'N/A')}")
    c.drawString(15 * mm, height - 44 * mm, f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # Mottaker
    c.setFont("Helvetica-Bold", 11)
    c.drawString(15 * mm, height - 60 * mm, "Recipient:")
    c.setFont("Helvetica", 10)
    c.drawString(15 * mm, height - 67 * mm, name)
    c.drawString(15 * mm, height - 74 * mm, addr1)
    c.drawString(15 * mm, height - 81 * mm, f"{zip_} {city}")
    c.drawString(15 * mm, height - 88 * mm, country)
    if phone:
        c.drawString(15 * mm, height - 95 * mm, f"Tel: {phone}")

    # Enkel Bring-logo placeholder (tekst)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(width - 60 * mm, height - 25 * mm, "BRING")

    # Tracking "strek"
    c.setLineWidth(2)
    c.line(15 * mm, height - 50 * mm, width - 15 * mm, height - 50 * mm)

    c.showPage()
    c.save()
    print(f"✅ PDF generated: {outfile}")


def generate_order_summary_pdf(orders: list, outfile):
    """
    Generer en PDF med flere ordre-etiketter på én side (A4),
    f.eks. for batch printing.
    """
    c = canvas.Canvas(str(outfile), pagesize=A4)
    width, height = A4

    c.setFont("Helvetica-Bold", 16)
    c.drawString(25 * mm, height - 25 * mm, "PackChicken Batch Label Summary")

    y = height - 40 * mm
    for i, order in enumerate(orders, start=1):
        ship = order.get("shipping_address", {})
        c.setFont("Helvetica-Bold", 11)
        c.drawString(25 * mm, y, f"{i}. {order.get('name', 'Ukjent')}")
        c.setFont("Helvetica", 10)
        c.drawString(25 * mm, y - 6 * mm, ship.get("address1", ""))
        c.drawString(25 * mm, y - 12 * mm, f"{ship.get('zip', '')} {ship.get('city', '')}")
        c.drawString(25 * mm, y - 18 * mm, ship.get("country", "NO"))
        y -= 30 * mm
        if y < 40 * mm:
            c.showPage()
            y = height - 40 * mm

    c.save()
    print(f"✅ Summary PDF generated: {outfile}")
