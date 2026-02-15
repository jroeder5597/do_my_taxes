"""
SQLite database handler for tax document storage.
Provides CRUD operations for all tax data models.
"""

import json
import sqlite3
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from .models import (
    Document,
    DocumentType,
    Form1099DIV,
    Form1099INT,
    ProcessingStatus,
    TaxYear,
    W2Data,
)


class SQLiteHandler:
    """
    SQLite database handler for tax document storage.
    """
    
    def __init__(self, database_path: str = "db/taxes.db"):
        """
        Initialize the database handler.
        
        Args:
            database_path: Path to the SQLite database file
        """
        self.database_path = Path(database_path)
        self._connection: Optional[sqlite3.Connection] = None
    
    @property
    def connection(self) -> sqlite3.Connection:
        """Get or create a database connection."""
        if self._connection is None:
            # Ensure directory exists
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            
            self._connection = sqlite3.connect(
                str(self.database_path),
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            )
            self._connection.row_factory = sqlite3.Row
            
            # Enable foreign keys
            self._connection.execute("PRAGMA foreign_keys = ON")
            
            # Create tables if they don't exist
            self._create_tables()
        
        return self._connection
    
    def close(self) -> None:
        """Close the database connection."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None
    
    def _create_tables(self) -> None:
        """Create all database tables."""
        cursor = self.connection.cursor()
        
        # Tax Years table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tax_years (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                year INTEGER UNIQUE NOT NULL,
                filing_status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Documents table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tax_year_id INTEGER NOT NULL REFERENCES tax_years(id),
                document_type TEXT NOT NULL,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                ocr_text TEXT,
                processing_status TEXT DEFAULT 'pending',
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # W-2 Data table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS w2_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL REFERENCES documents(id),
                employer_ein TEXT,
                employer_name TEXT NOT NULL,
                employer_address TEXT,
                employer_city TEXT,
                employer_state TEXT,
                employer_zip TEXT,
                employee_name TEXT NOT NULL,
                employee_ssn TEXT,
                employee_address TEXT,
                employee_city TEXT,
                employee_state TEXT,
                employee_zip TEXT,
                control_number TEXT,
                wages_tips_compensation DECIMAL(12,2) NOT NULL,
                federal_income_tax_withheld DECIMAL(12,2) NOT NULL,
                social_security_wages DECIMAL(12,2) NOT NULL,
                social_security_tax_withheld DECIMAL(12,2) NOT NULL,
                medicare_wages DECIMAL(12,2) NOT NULL,
                medicare_tax_withheld DECIMAL(12,2) NOT NULL,
                social_security_tips DECIMAL(12,2),
                allocated_tips DECIMAL(12,2),
                dependent_care_benefits DECIMAL(12,2),
                nonqualified_plans DECIMAL(12,2),
                box_12_codes TEXT,
                statutory_employee INTEGER DEFAULT 0,
                retirement_plan INTEGER DEFAULT 0,
                third_party_sick_pay INTEGER DEFAULT 0,
                box_14_other TEXT,
                state_employer_state_id TEXT,
                state_wages_tips DECIMAL(12,2),
                state_income_tax DECIMAL(12,2),
                local_wages_tips DECIMAL(12,2),
                local_income_tax DECIMAL(12,2),
                locality_name TEXT,
                raw_data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 1099-INT Data table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS form_1099_int (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL REFERENCES documents(id),
                payer_name TEXT NOT NULL,
                payer_address TEXT,
                payer_tin TEXT,
                recipient_name TEXT NOT NULL,
                recipient_tin TEXT,
                recipient_address TEXT,
                interest_income DECIMAL(12,2) NOT NULL,
                early_withdrawal_penalty DECIMAL(12,2),
                interest_on_us_savings_bonds DECIMAL(12,2),
                federal_income_tax_withheld DECIMAL(12,2),
                investment_expenses DECIMAL(12,2),
                foreign_tax_paid DECIMAL(12,2),
                foreign_country TEXT,
                tax_exempt_interest DECIMAL(12,2),
                specified_private_activity_bond_interest DECIMAL(12,2),
                market_discount DECIMAL(12,2),
                bond_premium DECIMAL(12,2),
                bond_premium_treasury_obligations DECIMAL(12,2),
                bond_premium_tax_exempt_bond DECIMAL(12,2),
                tax_exempt_cusip_number TEXT,
                state_info TEXT,
                raw_data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 1099-DIV Data table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS form_1099_div (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL REFERENCES documents(id),
                payer_name TEXT NOT NULL,
                payer_address TEXT,
                payer_tin TEXT,
                recipient_name TEXT NOT NULL,
                recipient_tin TEXT,
                recipient_address TEXT,
                total_ordinary_dividends DECIMAL(12,2) NOT NULL,
                qualified_dividends DECIMAL(12,2),
                total_capital_gain DECIMAL(12,2),
                unrecaptured_section_1250_gain DECIMAL(12,2),
                section_1202_gain DECIMAL(12,2),
                collectibles_gain DECIMAL(12,2),
                section_897_ordinary_dividends DECIMAL(12,2),
                section_897_capital_gain DECIMAL(12,2),
                nondividend_distributions DECIMAL(12,2),
                federal_income_tax_withheld DECIMAL(12,2),
                section_199a_dividends DECIMAL(12,2),
                investment_expenses DECIMAL(12,2),
                foreign_tax_paid DECIMAL(12,2),
                foreign_country TEXT,
                cash_liquidation DECIMAL(12,2),
                noncash_liquidation DECIMAL(12,2),
                fatca_filing INTEGER DEFAULT 0,
                state_info TEXT,
                raw_data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_tax_year 
            ON documents(tax_year_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_type 
            ON documents(document_type)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_status 
            ON documents(processing_status)
        """)
        
        self.connection.commit()
    
    # ==================== Tax Year Operations ====================
    
    def create_tax_year(self, year: int, filing_status: Optional[str] = None) -> TaxYear:
        """Create a new tax year record."""
        cursor = self.connection.cursor()
        
        cursor.execute("""
            INSERT INTO tax_years (year, filing_status)
            VALUES (?, ?)
        """, (year, filing_status))
        
        self.connection.commit()
        
        return TaxYear(
            id=cursor.lastrowid,
            year=year,
            filing_status=filing_status,
        )
    
    def get_tax_year(self, year: int) -> Optional[TaxYear]:
        """Get a tax year by year."""
        cursor = self.connection.cursor()
        
        cursor.execute("""
            SELECT id, year, filing_status, created_at
            FROM tax_years
            WHERE year = ?
        """, (year,))
        
        row = cursor.fetchone()
        
        if row is None:
            return None
        
        # Handle both string and datetime objects from SQLite
        created_at = row["created_at"]
        if created_at is not None and isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        
        return TaxYear(
            id=row["id"],
            year=row["year"],
            filing_status=row["filing_status"],
            created_at=created_at,
        )
    
    def get_or_create_tax_year(self, year: int) -> TaxYear:
        """Get or create a tax year record."""
        tax_year = self.get_tax_year(year)
        
        if tax_year is None:
            tax_year = self.create_tax_year(year)
        
        return tax_year
    
    def document_exists_by_hash(self, tax_year_id: int, file_hash: str) -> bool:
        """
        Check if a document with the given hash already exists for a tax year.
        
        Args:
            tax_year_id: Tax year ID
            file_hash: SHA256 hash of the file
        
        Returns:
            True if a document with this hash exists, False otherwise
        """
        cursor = self.connection.cursor()
        
        cursor.execute(
            """SELECT COUNT(1) FROM documents 
               WHERE tax_year_id = ? AND file_hash = ?""",
            (tax_year_id, file_hash)
        )
        
        return cursor.fetchone()[0] > 0
    
    def list_tax_years(self) -> list[TaxYear]:
        """List all tax years."""
        cursor = self.connection.cursor()
        
        cursor.execute("""
            SELECT id, year, filing_status, created_at
            FROM tax_years
            ORDER BY year DESC
        """)
        
        return [
            TaxYear(
                id=row["id"],
                year=row["year"],
                filing_status=row["filing_status"],
                created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
            )
            for row in cursor.fetchall()
        ]
    
    # ==================== Document Operations ====================
    
    def create_document(
        self,
        tax_year_id: int,
        document_type: DocumentType,
        file_name: str,
        file_path: str,
        file_hash: str,
    ) -> Document:
        """Create a new document record."""
        cursor = self.connection.cursor()
        
        cursor.execute("""
            INSERT INTO documents (tax_year_id, document_type, file_name, file_path, file_hash)
            VALUES (?, ?, ?, ?, ?)
        """, (tax_year_id, document_type.value, file_name, file_path, file_hash))
        
        self.connection.commit()
        
        return Document(
            id=cursor.lastrowid,
            tax_year_id=tax_year_id,
            document_type=document_type,
            file_name=file_name,
            file_path=file_path,
            file_hash=file_hash,
        )
    
    def get_document(self, document_id: int) -> Optional[Document]:
        """Get a document by ID."""
        cursor = self.connection.cursor()
        
        cursor.execute("""
            SELECT id, tax_year_id, document_type, file_name, file_path, 
                   file_hash, ocr_text, processing_status, error_message, 
                   created_at, updated_at
            FROM documents
            WHERE id = ?
        """, (document_id,))
        
        row = cursor.fetchone()
        
        if row is None:
            return None
        
        return Document(
            id=row["id"],
            tax_year_id=row["tax_year_id"],
            document_type=DocumentType(row["document_type"]),
            file_name=row["file_name"],
            file_path=row["file_path"],
            file_hash=row["file_hash"],
            ocr_text=row["ocr_text"],
            processing_status=ProcessingStatus(row["processing_status"]),
            error_message=row["error_message"],
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
        )
    
    def update_document_ocr_text(self, document_id: int, ocr_text: str) -> None:
        """Update the OCR text for a document."""
        cursor = self.connection.cursor()
        
        cursor.execute("""
            UPDATE documents
            SET ocr_text = ?, processing_status = 'ocr_complete', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (ocr_text, document_id))
        
        self.connection.commit()
    
    def update_document_status(
        self,
        document_id: int,
        status: ProcessingStatus,
        error_message: Optional[str] = None,
    ) -> None:
        """Update the processing status of a document."""
        cursor = self.connection.cursor()
        
        cursor.execute("""
            UPDATE documents
            SET processing_status = ?, error_message = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (status.value, error_message, document_id))
        
        self.connection.commit()
    
    def list_documents(
        self,
        tax_year_id: Optional[int] = None,
        document_type: Optional[DocumentType] = None,
        status: Optional[ProcessingStatus] = None,
    ) -> list[Document]:
        """List documents with optional filters."""
        cursor = self.connection.cursor()
        
        query = """
            SELECT id, tax_year_id, document_type, file_name, file_path, 
                   file_hash, ocr_text, processing_status, error_message, 
                   created_at, updated_at
            FROM documents
            WHERE 1=1
        """
        params: list[Any] = []
        
        if tax_year_id is not None:
            query += " AND tax_year_id = ?"
            params.append(tax_year_id)
        
        if document_type is not None:
            query += " AND document_type = ?"
            params.append(document_type.value)
        
        if status is not None:
            query += " AND processing_status = ?"
            params.append(status.value)
        
        query += " ORDER BY created_at DESC"
        
        cursor.execute(query, params)
        
        return [
            Document(
                id=row["id"],
                tax_year_id=row["tax_year_id"],
                document_type=DocumentType(row["document_type"]),
                file_name=row["file_name"],
                file_path=row["file_path"],
                file_hash=row["file_hash"],
                ocr_text=row["ocr_text"],
                processing_status=ProcessingStatus(row["processing_status"]),
                error_message=row["error_message"],
                created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
                updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
            )
            for row in cursor.fetchall()
        ]
    
    def delete_document(self, document_id: int) -> bool:
        """Delete a document and its associated data."""
        cursor = self.connection.cursor()
        
        # Delete associated form data first
        cursor.execute("DELETE FROM w2_data WHERE document_id = ?", (document_id,))
        cursor.execute("DELETE FROM form_1099_int WHERE document_id = ?", (document_id,))
        cursor.execute("DELETE FROM form_1099_div WHERE document_id = ?", (document_id,))
        
        # Delete the document
        cursor.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        
        self.connection.commit()
        
        return cursor.rowcount > 0
    
    # ==================== W-2 Data Operations ====================
    
    def save_w2_data(self, data: W2Data) -> W2Data:
        """Save W-2 form data."""
        cursor = self.connection.cursor()
        
        # Convert complex fields to JSON
        box_12_json = json.dumps([{"code": c.code, "amount": str(c.amount)} for c in data.box_12_codes])
        box_14_json = json.dumps([{"description": i.description, "amount": str(i.amount) if i.amount else None} for i in data.box_14_other])
        raw_data_json = json.dumps(data.raw_data) if data.raw_data else None
        
        cursor.execute("""
            INSERT INTO w2_data (
                document_id, employer_ein, employer_name, employer_address,
                employer_city, employer_state, employer_zip,
                employee_name, employee_ssn, employee_address,
                employee_city, employee_state, employee_zip,
                control_number, wages_tips_compensation, federal_income_tax_withheld,
                social_security_wages, social_security_tax_withheld,
                medicare_wages, medicare_tax_withheld,
                social_security_tips, allocated_tips,
                dependent_care_benefits, nonqualified_plans,
                box_12_codes, statutory_employee, retirement_plan, third_party_sick_pay,
                box_14_other, state_employer_state_id, state_wages_tips,
                state_income_tax, local_wages_tips, local_income_tax, locality_name,
                raw_data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.document_id, data.employer_ein, data.employer_name, data.employer_address,
            data.employer_city, data.employer_state, data.employer_zip,
            data.employee_name, data.employee_ssn, data.employee_address,
            data.employee_city, data.employee_state, data.employee_zip,
            data.control_number, str(data.wages_tips_compensation), str(data.federal_income_tax_withheld),
            str(data.social_security_wages), str(data.social_security_tax_withheld),
            str(data.medicare_wages), str(data.medicare_tax_withheld),
            str(data.social_security_tips) if data.social_security_tips else None,
            str(data.allocated_tips) if data.allocated_tips else None,
            str(data.dependent_care_benefits) if data.dependent_care_benefits else None,
            str(data.nonqualified_plans) if data.nonqualified_plans else None,
            box_12_json, 1 if data.statutory_employee else 0, 1 if data.retirement_plan else 0, 1 if data.third_party_sick_pay else 0,
            box_14_json, data.state_employer_state_id,
            str(data.state_wages_tips) if data.state_wages_tips else None,
            str(data.state_income_tax) if data.state_income_tax else None,
            str(data.local_wages_tips) if data.local_wages_tips else None,
            str(data.local_income_tax) if data.local_income_tax else None,
            data.locality_name, raw_data_json
        ))
        
        self.connection.commit()
        
        data.id = cursor.lastrowid
        
        # Update document status
        self.update_document_status(data.document_id, ProcessingStatus.EXTRACTED)
        
        return data
    
    def get_w2_data(self, document_id: int) -> Optional[W2Data]:
        """Get W-2 data for a document."""
        cursor = self.connection.cursor()
        
        cursor.execute("""
            SELECT * FROM w2_data WHERE document_id = ?
        """, (document_id,))
        
        row = cursor.fetchone()
        
        if row is None:
            return None
        
        return self._row_to_w2_data(row)
    
    def list_w2_data(self, tax_year_id: int) -> list[W2Data]:
        """List all W-2 data for a tax year."""
        cursor = self.connection.cursor()
        
        cursor.execute("""
            SELECT w.* FROM w2_data w
            JOIN documents d ON w.document_id = d.id
            WHERE d.tax_year_id = ?
            ORDER BY w.employer_name
        """, (tax_year_id,))
        
        return [self._row_to_w2_data(row) for row in cursor.fetchall()]
    
    def _row_to_w2_data(self, row: sqlite3.Row) -> W2Data:
        """Convert a database row to W2Data model."""
        # Parse JSON fields
        box_12_codes = []
        if row["box_12_codes"]:
            for item in json.loads(row["box_12_codes"]):
                from .models import Box12Code
                box_12_codes.append(Box12Code(
                    code=item["code"],
                    amount=Decimal(item["amount"]),
                ))
        
        box_14_other = []
        if row["box_14_other"]:
            for item in json.loads(row["box_14_other"]):
                from .models import Box14Item
                box_14_other.append(Box14Item(
                    description=item["description"],
                    amount=Decimal(item["amount"]) if item.get("amount") else None,
                ))
        
        raw_data = json.loads(row["raw_data"]) if row["raw_data"] else None
        
        return W2Data(
            id=row["id"],
            document_id=row["document_id"],
            employer_ein=row["employer_ein"],
            employer_name=row["employer_name"],
            employer_address=row["employer_address"],
            employer_city=row["employer_city"],
            employer_state=row["employer_state"],
            employer_zip=row["employer_zip"],
            employee_name=row["employee_name"],
            employee_ssn=row["employee_ssn"],
            employee_address=row["employee_address"],
            employee_city=row["employee_city"],
            employee_state=row["employee_state"],
            employee_zip=row["employee_zip"],
            control_number=row["control_number"],
            wages_tips_compensation=Decimal(row["wages_tips_compensation"]),
            federal_income_tax_withheld=Decimal(row["federal_income_tax_withheld"]),
            social_security_wages=Decimal(row["social_security_wages"]),
            social_security_tax_withheld=Decimal(row["social_security_tax_withheld"]),
            medicare_wages=Decimal(row["medicare_wages"]),
            medicare_tax_withheld=Decimal(row["medicare_tax_withheld"]),
            social_security_tips=Decimal(row["social_security_tips"]) if row["social_security_tips"] else None,
            allocated_tips=Decimal(row["allocated_tips"]) if row["allocated_tips"] else None,
            dependent_care_benefits=Decimal(row["dependent_care_benefits"]) if row["dependent_care_benefits"] else None,
            nonqualified_plans=Decimal(row["nonqualified_plans"]) if row["nonqualified_plans"] else None,
            box_12_codes=box_12_codes,
            statutory_employee=bool(row["statutory_employee"]),
            retirement_plan=bool(row["retirement_plan"]),
            third_party_sick_pay=bool(row["third_party_sick_pay"]),
            box_14_other=box_14_other,
            state_employer_state_id=row["state_employer_state_id"],
            state_wages_tips=Decimal(row["state_wages_tips"]) if row["state_wages_tips"] else None,
            state_income_tax=Decimal(row["state_income_tax"]) if row["state_income_tax"] else None,
            local_wages_tips=Decimal(row["local_wages_tips"]) if row["local_wages_tips"] else None,
            local_income_tax=Decimal(row["local_income_tax"]) if row["local_income_tax"] else None,
            locality_name=row["locality_name"],
            raw_data=raw_data,
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
        )
    
    # ==================== 1099-INT Data Operations ====================
    
    def save_1099_int_data(self, data: Form1099INT) -> Form1099INT:
        """Save 1099-INT form data."""
        cursor = self.connection.cursor()
        
        state_info_json = json.dumps([s.model_dump() for s in data.state_info])
        raw_data_json = json.dumps(data.raw_data) if data.raw_data else None
        
        cursor.execute("""
            INSERT INTO form_1099_int (
                document_id, payer_name, payer_address, payer_tin,
                recipient_name, recipient_tin, recipient_address,
                interest_income, early_withdrawal_penalty, interest_on_us_savings_bonds,
                federal_income_tax_withheld, investment_expenses,
                foreign_tax_paid, foreign_country,
                tax_exempt_interest, specified_private_activity_bond_interest,
                market_discount, bond_premium,
                bond_premium_treasury_obligations, bond_premium_tax_exempt_bond,
                tax_exempt_cusip_number, state_info, raw_data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.document_id, data.payer_name, data.payer_address, data.payer_tin,
            data.recipient_name, data.recipient_tin, data.recipient_address,
            str(data.interest_income),
            str(data.early_withdrawal_penalty) if data.early_withdrawal_penalty else None,
            str(data.interest_on_us_savings_bonds) if data.interest_on_us_savings_bonds else None,
            str(data.federal_income_tax_withheld) if data.federal_income_tax_withheld else None,
            str(data.investment_expenses) if data.investment_expenses else None,
            str(data.foreign_tax_paid) if data.foreign_tax_paid else None,
            data.foreign_country,
            str(data.tax_exempt_interest) if data.tax_exempt_interest else None,
            str(data.specified_private_activity_bond_interest) if data.specified_private_activity_bond_interest else None,
            str(data.market_discount) if data.market_discount else None,
            str(data.bond_premium) if data.bond_premium else None,
            str(data.bond_premium_treasury_obligations) if data.bond_premium_treasury_obligations else None,
            str(data.bond_premium_tax_exempt_bond) if data.bond_premium_tax_exempt_bond else None,
            data.tax_exempt_cusip_number, state_info_json, raw_data_json
        ))
        
        self.connection.commit()
        
        data.id = cursor.lastrowid
        self.update_document_status(data.document_id, ProcessingStatus.EXTRACTED)
        
        return data
    
    def get_1099_int_data(self, document_id: int) -> Optional[Form1099INT]:
        """Get 1099-INT data for a document."""
        cursor = self.connection.cursor()
        
        cursor.execute("SELECT * FROM form_1099_int WHERE document_id = ?", (document_id,))
        row = cursor.fetchone()
        
        if row is None:
            return None
        
        return self._row_to_1099_int(row)
    
    def list_1099_int_data(self, tax_year_id: int) -> list[Form1099INT]:
        """List all 1099-INT data for a tax year."""
        cursor = self.connection.cursor()
        
        cursor.execute("""
            SELECT f.* FROM form_1099_int f
            JOIN documents d ON f.document_id = d.id
            WHERE d.tax_year_id = ?
            ORDER BY f.payer_name
        """, (tax_year_id,))
        
        return [self._row_to_1099_int(row) for row in cursor.fetchall()]
    
    def _row_to_1099_int(self, row: sqlite3.Row) -> Form1099INT:
        """Convert a database row to Form1099INT model."""
        from .models import StateInfo
        
        state_info = []
        if row["state_info"]:
            for item in json.loads(row["state_info"]):
                state_info.append(StateInfo(**item))
        
        raw_data = json.loads(row["raw_data"]) if row["raw_data"] else None
        
        return Form1099INT(
            id=row["id"],
            document_id=row["document_id"],
            payer_name=row["payer_name"],
            payer_address=row["payer_address"],
            payer_tin=row["payer_tin"],
            recipient_name=row["recipient_name"],
            recipient_tin=row["recipient_tin"],
            recipient_address=row["recipient_address"],
            interest_income=Decimal(row["interest_income"]),
            early_withdrawal_penalty=Decimal(row["early_withdrawal_penalty"]) if row["early_withdrawal_penalty"] else None,
            interest_on_us_savings_bonds=Decimal(row["interest_on_us_savings_bonds"]) if row["interest_on_us_savings_bonds"] else None,
            federal_income_tax_withheld=Decimal(row["federal_income_tax_withheld"]) if row["federal_income_tax_withheld"] else None,
            investment_expenses=Decimal(row["investment_expenses"]) if row["investment_expenses"] else None,
            foreign_tax_paid=Decimal(row["foreign_tax_paid"]) if row["foreign_tax_paid"] else None,
            foreign_country=row["foreign_country"],
            tax_exempt_interest=Decimal(row["tax_exempt_interest"]) if row["tax_exempt_interest"] else None,
            specified_private_activity_bond_interest=Decimal(row["specified_private_activity_bond_interest"]) if row["specified_private_activity_bond_interest"] else None,
            market_discount=Decimal(row["market_discount"]) if row["market_discount"] else None,
            bond_premium=Decimal(row["bond_premium"]) if row["bond_premium"] else None,
            bond_premium_treasury_obligations=Decimal(row["bond_premium_treasury_obligations"]) if row["bond_premium_treasury_obligations"] else None,
            bond_premium_tax_exempt_bond=Decimal(row["bond_premium_tax_exempt_bond"]) if row["bond_premium_tax_exempt_bond"] else None,
            tax_exempt_cusip_number=row["tax_exempt_cusip_number"],
            state_info=state_info,
            raw_data=raw_data,
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
        )
    
    # ==================== 1099-DIV Data Operations ====================
    
    def save_1099_div_data(self, data: Form1099DIV) -> Form1099DIV:
        """Save 1099-DIV form data."""
        cursor = self.connection.cursor()
        
        state_info_json = json.dumps([s.model_dump() for s in data.state_info])
        raw_data_json = json.dumps(data.raw_data) if data.raw_data else None
        
        cursor.execute("""
            INSERT INTO form_1099_div (
                document_id, payer_name, payer_address, payer_tin,
                recipient_name, recipient_tin, recipient_address,
                total_ordinary_dividends, qualified_dividends,
                total_capital_gain, unrecaptured_section_1250_gain,
                section_1202_gain, collectibles_gain,
                section_897_ordinary_dividends, section_897_capital_gain,
                nondividend_distributions, federal_income_tax_withheld,
                section_199a_dividends, investment_expenses,
                foreign_tax_paid, foreign_country,
                cash_liquidation, noncash_liquidation,
                fatca_filing, state_info, raw_data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.document_id, data.payer_name, data.payer_address, data.payer_tin,
            data.recipient_name, data.recipient_tin, data.recipient_address,
            str(data.total_ordinary_dividends),
            str(data.qualified_dividends) if data.qualified_dividends else None,
            str(data.total_capital_gain) if data.total_capital_gain else None,
            str(data.unrecaptured_section_1250_gain) if data.unrecaptured_section_1250_gain else None,
            str(data.section_1202_gain) if data.section_1202_gain else None,
            str(data.collectibles_gain) if data.collectibles_gain else None,
            str(data.section_897_ordinary_dividends) if data.section_897_ordinary_dividends else None,
            str(data.section_897_capital_gain) if data.section_897_capital_gain else None,
            str(data.nondividend_distributions) if data.nondividend_distributions else None,
            str(data.federal_income_tax_withheld) if data.federal_income_tax_withheld else None,
            str(data.section_199a_dividends) if data.section_199a_dividends else None,
            str(data.investment_expenses) if data.investment_expenses else None,
            str(data.foreign_tax_paid) if data.foreign_tax_paid else None,
            data.foreign_country,
            str(data.cash_liquidation) if data.cash_liquidation else None,
            str(data.noncash_liquidation) if data.noncash_liquidation else None,
            1 if data.fatca_filing else 0,
            state_info_json, raw_data_json
        ))
        
        self.connection.commit()
        
        data.id = cursor.lastrowid
        self.update_document_status(data.document_id, ProcessingStatus.EXTRACTED)
        
        return data
    
    def get_1099_div_data(self, document_id: int) -> Optional[Form1099DIV]:
        """Get 1099-DIV data for a document."""
        cursor = self.connection.cursor()
        
        cursor.execute("SELECT * FROM form_1099_div WHERE document_id = ?", (document_id,))
        row = cursor.fetchone()
        
        if row is None:
            return None
        
        return self._row_to_1099_div(row)
    
    def list_1099_div_data(self, tax_year_id: int) -> list[Form1099DIV]:
        """List all 1099-DIV data for a tax year."""
        cursor = self.connection.cursor()
        
        cursor.execute("""
            SELECT f.* FROM form_1099_div f
            JOIN documents d ON f.document_id = d.id
            WHERE d.tax_year_id = ?
            ORDER BY f.payer_name
        """, (tax_year_id,))
        
        return [self._row_to_1099_div(row) for row in cursor.fetchall()]
    
    def _row_to_1099_div(self, row: sqlite3.Row) -> Form1099DIV:
        """Convert a database row to Form1099DIV model."""
        from .models import StateInfo
        
        state_info = []
        if row["state_info"]:
            for item in json.loads(row["state_info"]):
                state_info.append(StateInfo(**item))
        
        raw_data = json.loads(row["raw_data"]) if row["raw_data"] else None
        
        return Form1099DIV(
            id=row["id"],
            document_id=row["document_id"],
            payer_name=row["payer_name"],
            payer_address=row["payer_address"],
            payer_tin=row["payer_tin"],
            recipient_name=row["recipient_name"],
            recipient_tin=row["recipient_tin"],
            recipient_address=row["recipient_address"],
            total_ordinary_dividends=Decimal(row["total_ordinary_dividends"]),
            qualified_dividends=Decimal(row["qualified_dividends"]) if row["qualified_dividends"] else None,
            total_capital_gain=Decimal(row["total_capital_gain"]) if row["total_capital_gain"] else None,
            unrecaptured_section_1250_gain=Decimal(row["unrecaptured_section_1250_gain"]) if row["unrecaptured_section_1250_gain"] else None,
            section_1202_gain=Decimal(row["section_1202_gain"]) if row["section_1202_gain"] else None,
            collectibles_gain=Decimal(row["collectibles_gain"]) if row["collectibles_gain"] else None,
            section_897_ordinary_dividends=Decimal(row["section_897_ordinary_dividends"]) if row["section_897_ordinary_dividends"] else None,
            section_897_capital_gain=Decimal(row["section_897_capital_gain"]) if row["section_897_capital_gain"] else None,
            nondividend_distributions=Decimal(row["nondividend_distributions"]) if row["nondividend_distributions"] else None,
            federal_income_tax_withheld=Decimal(row["federal_income_tax_withheld"]) if row["federal_income_tax_withheld"] else None,
            section_199a_dividends=Decimal(row["section_199a_dividends"]) if row["section_199a_dividends"] else None,
            investment_expenses=Decimal(row["investment_expenses"]) if row["investment_expenses"] else None,
            foreign_tax_paid=Decimal(row["foreign_tax_paid"]) if row["foreign_tax_paid"] else None,
            foreign_country=row["foreign_country"],
            cash_liquidation=Decimal(row["cash_liquidation"]) if row["cash_liquidation"] else None,
            noncash_liquidation=Decimal(row["noncash_liquidation"]) if row["noncash_liquidation"] else None,
            fatca_filing=bool(row["fatca_filing"]),
            state_info=state_info,
            raw_data=raw_data,
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
        )
    
    # ==================== Summary Operations ====================
    
    def get_tax_summary(self, tax_year_id: int) -> dict:
        """Get a summary of all tax data for a year."""
        summary = {
            "w2_count": 0,
            "total_wages": Decimal("0"),
            "total_federal_withheld": Decimal("0"),
            "total_state_withheld": Decimal("0"),
            "form_1099_int_count": 0,
            "total_interest": Decimal("0"),
            "form_1099_div_count": 0,
            "total_dividends": Decimal("0"),
            "total_qualified_dividends": Decimal("0"),
        }
        
        # W-2 Summary
        w2_list = self.list_w2_data(tax_year_id)
        summary["w2_count"] = len(w2_list)
        for w2 in w2_list:
            summary["total_wages"] += w2.wages_tips_compensation
            summary["total_federal_withheld"] += w2.federal_income_tax_withheld
            if w2.state_income_tax:
                summary["total_state_withheld"] += w2.state_income_tax
        
        # 1099-INT Summary
        int_list = self.list_1099_int_data(tax_year_id)
        summary["form_1099_int_count"] = len(int_list)
        for form in int_list:
            summary["total_interest"] += form.interest_income
            if form.federal_income_tax_withheld:
                summary["total_federal_withheld"] += form.federal_income_tax_withheld
        
        # 1099-DIV Summary
        div_list = self.list_1099_div_data(tax_year_id)
        summary["form_1099_div_count"] = len(div_list)
        for form in div_list:
            summary["total_dividends"] += form.total_ordinary_dividends
            if form.qualified_dividends:
                summary["total_qualified_dividends"] += form.qualified_dividends
            if form.federal_income_tax_withheld:
                summary["total_federal_withheld"] += form.federal_income_tax_withheld
        
        return summary