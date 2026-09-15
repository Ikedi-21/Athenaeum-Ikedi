"""
Management command to seed realistic sample data for Athenaeum Ikedi.
Creates categories, verified books, student accounts, active loans, and audit logs.
"""

from datetime import timedelta
from decimal import Decimal
import random

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import User
from catalog.models import Book, Category, Review
from circulation.models import AuditAction, AuditLog, BorrowRecord, Reservation, ReservationStatus


def calculate_isbn13_check_digit(nine_plus_three):
    """Given 12 digits, return the valid 13th check digit for ISBN-13."""
    total = sum(
        int(digit) * (1 if idx % 2 == 0 else 3)
        for idx, digit in enumerate(nine_plus_three)
    )
    rem = total % 10
    return "0" if rem == 0 else str(10 - rem)


class Command(BaseCommand):
    help = "Seeds categories, books, students, and circulation records."

    def handle(self, *args, **options):
        self.stdout.write("Seeding Athenaeum Ikedi library data...")

        # 1. Categories
        categories_data = [
            ("Computer Science & AI", "Algorithms, operating systems, distributed computing, and artificial intelligence."),
            ("African Literature & Classics", "Landmark works of African fiction, drama, poetry, and post-colonial studies."),
            ("Economics & Finance", "Microeconomics, macroeconomic theory, public policy, and corporate valuation."),
            ("Philosophy & Jurisprudence", "Epistemology, ethics, legal philosophy, and constitutional theory."),
            ("Pure & Applied Mathematics", "Calculus, linear algebra, number theory, and discrete structures."),
        ]

        categories = {}
        for name, desc in categories_data:
            cat, _ = Category.objects.get_or_create(
                name=name,
                defaults={"description": desc}
            )
            categories[name] = cat
        self.stdout.write(self.style.SUCCESS(f"Created {len(categories)} categories."))

        # 2. Books with guaranteed valid ISBNs
        books_raw = [
            (
                "Structure and Interpretation of Computer Programs",
                "Harold Abelson, Gerald Jay Sussman",
                "978026251087",
                "Computer Science & AI",
                "Classic foundational text on computer programming using Lisp and Scheme.",
                5,
            ),
            (
                "Introduction to Algorithms (CLRS)",
                "Thomas H. Cormen, Charles E. Leiserson",
                "978026203384",
                "Computer Science & AI",
                "The definitive reference guide to algorithms and data structures.",
                4,
            ),
            (
                "Designing Data-Intensive Applications",
                "Martin Kleppmann",
                "978144937332",
                "Computer Science & AI",
                "The fundamental principles of distributed data systems and storage engines.",
                3,
            ),
            (
                "Things Fall Apart",
                "Chinua Achebe",
                "978038547454",
                "African Literature & Classics",
                "Masterpiece exploring pre-colonial life in southeastern Nigeria and colonial invasion.",
                6,
            ),
            (
                "Half of a Yellow Sun",
                "Chimamanda Ngozi Adichie",
                "978140009520",
                "African Literature & Classics",
                "Stunning historical epic about the Biafran war and human resilience.",
                4,
            ),
            (
                "Death and the King's Horseman",
                "Wole Soyinka",
                "978041369550",
                "African Literature & Classics",
                "Nobel laureate Wole Soyinka's tragic drama based on a real event in colonial Nigeria.",
                3,
            ),
            (
                "Principles of Economics",
                "N. Gregory Mankiw",
                "978130558512",
                "Economics & Finance",
                "The gold standard introduction to micro and macroeconomic principles.",
                4,
            ),
            (
                "Capital in the Twenty-First Century",
                "Thomas Piketty",
                "978067443000",
                "Economics & Finance",
                "Seminal investigation of wealth and income inequality across two centuries.",
                3,
            ),
            (
                "The Concept of Law",
                "H. L. A. Hart",
                "978019964470",
                "Philosophy & Jurisprudence",
                "A foundational analysis of legal positivism, legal rules, and the nature of society.",
                3,
            ),
            (
                "Linear Algebra and Its Applications",
                "Gilbert Strang",
                "978003010567",
                "Pure & Applied Mathematics",
                "Accessible and rigorous development of vector spaces and matrix theory.",
                4,
            ),
        ]

        books = []
        for title, author, isbn_base, cat_name, desc, qty in books_raw:
            check_digit = calculate_isbn13_check_digit(isbn_base)
            full_isbn = isbn_base + check_digit
            cat = categories[cat_name]

            book, created = Book.objects.get_or_create(
                isbn=full_isbn,
                defaults={
                    "title": title,
                    "author": author,
                    "category": cat,
                    "description": desc,
                    "quantity": qty,
                    "available_quantity": qty,
                    "published_date": timezone.localdate() - timedelta(days=random.randint(400, 3000)),
                }
            )
            books.append(book)

        self.stdout.write(self.style.SUCCESS(f"Created {len(books)} book titles."))

        # 3. Extra Student Users
        students_raw = [
            ("amaka_okafor", "Amaka", "Okafor", "amaka.okafor@athenaeum.edu"),
            ("chidi_ezekiel", "Chidi", "Ezekiel", "chidi.ezekiel@athenaeum.edu"),
            ("zainab_bello", "Zainab", "Bello", "zainab.bello@athenaeum.edu"),
        ]

        students = []
        # include existing franklin student
        franklin = User.objects.filter(username="franklinikedinahi").first()
        if franklin:
            students.append(franklin)

        for uname, fname, lname, email in students_raw:
            user, created = User.objects.get_or_create(
                username=uname,
                defaults={
                    "first_name": fname,
                    "last_name": lname,
                    "email": email,
                    "role": User.Role.STUDENT,
                }
            )
            if created:
                user.set_password("LibraryPass123!")
                user.save()
            students.append(user)

        self.stdout.write(self.style.SUCCESS(f"Active student pool: {len(students)} members."))

        # 4. Realistic Loans & Circulation State
        today = timezone.localdate()
        librarian = User.objects.filter(role=User.Role.LIBRARIAN).first()

        if franklin and len(books) >= 4:
            # Clean up old records for clean seed
            BorrowRecord.objects.filter(student=franklin).delete()

            # Active loan 1: On time
            b1 = books[0]
            if b1.available_quantity > 0:
                b1.available_quantity -= 1
                b1.save()
                rec1 = BorrowRecord.objects.create(
                    student=franklin,
                    book=b1,
                    due_date=today + timedelta(days=9),
                )
                BorrowRecord.objects.filter(pk=rec1.pk).update(
                    borrowed_date=timezone.now() - timedelta(days=5)
                )

            # Active loan 2: Overdue (by 3 days)
            b2 = books[3]
            if b2.available_quantity > 0:
                b2.available_quantity -= 1
                b2.save()
                rec2 = BorrowRecord.objects.create(
                    student=franklin,
                    book=b2,
                    due_date=today - timedelta(days=3),
                )
                BorrowRecord.objects.filter(pk=rec2.pk).update(
                    borrowed_date=timezone.now() - timedelta(days=17)
                )

            # Historical loan with paid fine
            b3 = books[1]
            rec3 = BorrowRecord.objects.create(
                student=franklin,
                book=b3,
                due_date=today - timedelta(days=26),
                fine_amount=Decimal("200.00"),
                fine_paid=True,
            )
            BorrowRecord.objects.filter(pk=rec3.pk).update(
                borrowed_date=timezone.now() - timedelta(days=40),
                returned_date=timezone.now() - timedelta(days=22),
            )

            # Reservation: Hold ready
            b4 = books[4]
            Reservation.objects.filter(student=franklin).delete()
            Reservation.objects.create(
                student=franklin,
                book=b4,
                status=ReservationStatus.NOTIFIED,
                notified_date=timezone.now() - timedelta(days=1),
                expires_date=timezone.now() + timedelta(days=2),
            )

            # Reviews
            Review.objects.filter(student=franklin).delete()
            Review.objects.create(
                student=franklin,
                book=b1,
                rating=5,
                comment="A truly transformative foundational book. The concepts on computational processes are unmatched.",
            )

        # 5. Some loans for other students
        if len(students) > 1 and len(books) >= 6:
            s2 = students[1]
            b5 = books[2]
            if b5.available_quantity > 0:
                b5.available_quantity -= 1
                b5.save()
                rec5 = BorrowRecord.objects.create(
                    student=s2,
                    book=b5,
                    due_date=today + timedelta(days=11),
                )
                BorrowRecord.objects.filter(pk=rec5.pk).update(
                    borrowed_date=timezone.now() - timedelta(days=3)
                )

        # 6. Audit Trail entries
        if librarian:
            AuditLog.objects.all().delete()
            AuditLog.objects.create(
                user=librarian,
                action=AuditAction.BOOK_CREATE,
                target="Book: Structure and Interpretation of Computer Programs",
                detail="Created initial catalogue record with 5 accession copies.",
                ip_address="127.0.0.1",
            )
            AuditLog.objects.create(
                user=librarian,
                action=AuditAction.BORROW,
                target="Loan: Things Fall Apart to franklinikedinahi",
                detail="Issued 1 copy at circulation desk.",
                ip_address="127.0.0.1",
            )
            AuditLog.objects.create(
                user=librarian,
                action=AuditAction.FINE_PAID,
                target="Fine: 200.00 naira for Introduction to Algorithms",
                detail="Payment received in cash and cleared.",
                ip_address="127.0.0.1",
            )

        self.stdout.write(self.style.SUCCESS("Library successfully seeded with realistic catalogue and circulation records!"))
