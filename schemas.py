from pydantic import BaseModel, field_validator, computed_field
from typing import Optional, List
import re



# ─── Product ─────────────────────────────────────────────────────────────────

class ProductBase(BaseModel):
    name: str
    category: str
    unit: str
    price: float
    desc: Optional[str] = ""
    hsn_code: Optional[str] = ""
    manufacturing_materials_json: Optional[str] = "[]"


class ProductCreate(ProductBase):
    pass


class ProductUpdate(ProductBase):
    pass


class ProductOut(ProductBase):
    id: str
    quote_count: Optional[int] = 0

    model_config = {"from_attributes": True}


# ─── Customer ────────────────────────────────────────────────────────────────

class CustomerBase(BaseModel):
    name: str
    phone: Optional[str] = ""
    email: Optional[str] = ""
    city: Optional[str] = ""
    address: Optional[str] = ""
    gstin: Optional[str] = ""
    store_images_json: Optional[str] = "[]"
    store_videos_json: Optional[str] = "[]"
    store_width: Optional[float] = None
    store_length: Optional[float] = None
    store_height: Optional[float] = None
    store_area: Optional[float] = None



class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(CustomerBase):
    pass


class CustomerOut(CustomerBase):
    id: str
    created_at: int
    total_quotes: Optional[int] = 0
    total_revenue: Optional[float] = 0.0
    last_quote_date: Optional[str] = None

    model_config = {"from_attributes": True}


# ─── Quotation ────────────────────────────────────────────────────────────────

class LineItem(BaseModel):
    name: Optional[str] = "Item"
    category: Optional[str] = "Standard"
    unit: Optional[str] = "Pcs"
    price: Optional[float] = 0.0
    qty: Optional[float] = 1.0
    line_total: Optional[float] = 0.0
    hsn_code: Optional[str] = ""
    gst_rate: Optional[float] = 18.0
    desc: Optional[str] = ""
    description: Optional[str] = ""
    remarks: Optional[str] = ""
    image: Optional[str] = ""
    product_image: Optional[str] = ""



class CustomerInfo(BaseModel):
    name: str
    phone: Optional[str] = ""
    email: Optional[str] = ""
    city: Optional[str] = ""
    address: Optional[str] = ""
    gstin: Optional[str] = ""


class Totals(BaseModel):
    subtotal: float
    delivery: float
    discount_percent: float
    discount_amount: float
    gst_rate: float
    gst_amount: float
    cgst: float
    sgst: float
    igst: float
    grand_total: float
    gst_type: Optional[str] = "exclusive"
    gst_inclusive: Optional[bool] = False


class QuotationCreate(BaseModel):
    quote_number: str
    date: str
    customer_id: Optional[str] = None
    customer: CustomerInfo
    items: List[LineItem]
    gst_mode: str
    totals: Totals
    terms: List[str]
    validity_days: Optional[int] = 15
    payment_type: Optional[str] = "advance_50"
    status: Optional[str] = "Draft"
    payment_status: Optional[str] = "Pending"
    gst_type: Optional[str] = "exclusive"
    gst_inclusive: Optional[bool] = False


class QuotationOut(BaseModel):
    id: str
    quote_number: str
    date: str
    customer_id: Optional[str] = None
    customer: CustomerInfo
    items: List[LineItem]
    gst_mode: str
    totals: Totals
    terms: List[str]
    validity_days: int
    payment_type: str
    status: str
    payment_status: str
    gst_type: str
    gst_inclusive: bool
    created_at: int

    model_config = {"from_attributes": True}


# ─── Payment ──────────────────────────────────────────────────────────────────

class PaymentBase(BaseModel):
    quotation_id: str
    customer_id: str
    invoice_number: str
    payment_type: str  # Advance | Final | Full Payment
    amount: float
    payment_date: int  # epoch milliseconds
    payment_mode: str  # Cash | UPI | Bank Transfer | Cheque
    transaction_id: Optional[str] = ""
    remarks: Optional[str] = ""
    created_by: Optional[str] = "Admin"


class PaymentCreate(PaymentBase):
    pass


class PaymentOut(PaymentBase):
    id: str

    model_config = {"from_attributes": True}


# ─── Salesman ────────────────────────────────────────────────────────────────

class SalesmanCreate(BaseModel):
    name: str
    phone: Optional[str] = ""
    email: str
    password: str
    confirm_password: str
    area: Optional[str] = ""
    employee_id: str

    @field_validator("email")
    @classmethod
    def check_email(cls, v):
        if not v or not re.match(r"^[^@]+@[^@]+\.[^@]+$", v.strip()):
            raise ValueError("Invalid email format.")
        return v.strip().lower()


class SalesmanUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    pin: Optional[str] = None
    password: Optional[str] = None
    confirm_password: Optional[str] = None
    area: Optional[str] = None
    active: Optional[bool] = None


class SalesmanOut(BaseModel):
    id: str
    name: str
    phone: str
    email: Optional[str] = ""
    area: str
    active: bool
    created_at: int
    lead_count: Optional[int] = 0

    model_config = {"from_attributes": True}


class SalesmanLogin(BaseModel):
    name: str
    pin: str


# ─── Telecaller ──────────────────────────────────────────────────────────────

class TelecallerCreate(BaseModel):
    name: str
    phone: Optional[str] = ""
    email: str
    password: str
    confirm_password: str
    employee_id: str

    @field_validator("email")
    @classmethod
    def check_email(cls, v):
        if not v or not re.match(r"^[^@]+@[^@]+\.[^@]+$", v.strip()):
            raise ValueError("Invalid email format.")
        return v.strip().lower()


class TelecallerUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    pin: Optional[str] = None
    password: Optional[str] = None
    confirm_password: Optional[str] = None
    active: Optional[bool] = None


class TelecallerOut(BaseModel):
    id: str
    name: str
    phone: str
    email: Optional[str] = ""
    active: bool
    created_at: int
    lead_count: Optional[int] = 0

    model_config = {"from_attributes": True}


class TelecallerLogin(BaseModel):
    name: str
    pin: str


# ─── Factory User ─────────────────────────────────────────────────────────────

class FactoryUserCreate(BaseModel):
    name: str
    email: str
    phone: Optional[str] = ""
    employee_id: str
    password: str
    confirm_password: str

    @field_validator("email")
    @classmethod
    def check_email(cls, v):
        if not v or not re.match(r"^[^@]+@[^@]+\.[^@]+$", v.strip()):
            raise ValueError("Invalid email format.")
        return v.strip().lower()


class FactoryUserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    password: Optional[str] = None
    confirm_password: Optional[str] = None
    is_active: Optional[bool] = None


class FactoryUserOut(BaseModel):
    id: str
    name: str
    email: str
    phone: Optional[str] = ""
    employee_id: str
    username: str
    is_active: bool
    created_at: int

    model_config = {"from_attributes": True}



class LeadCreate(BaseModel):
    salesman_id: Optional[str] = ""
    salesman_name: Optional[str] = ""
    created_by_id: Optional[str] = ""
    created_by_name: Optional[str] = ""
    created_by_role: Optional[str] = ""
    customer_name: str
    phone: Optional[str] = ""
    shop_name: Optional[str] = ""
    address: Optional[str] = ""
    city: Optional[str] = ""
    pincode: Optional[str] = ""
    business_type: Optional[str] = ""
    remarks: Optional[str] = ""
    follow_up_date: Optional[str] = ""
    created_note: Optional[str] = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    photo: Optional[str] = ""
    lead_source: Optional[str] = ""
    store_images_json: Optional[str] = "[]"
    store_videos_json: Optional[str] = "[]"
    status: Optional[str] = None
    facebook_lead_id: Optional[str] = ""
    campaign_id: Optional[str] = ""
    campaign_name: Optional[str] = ""
    adset_id: Optional[str] = ""
    adset_name: Optional[str] = ""
    ad_id: Optional[str] = ""
    ad_name: Optional[str] = ""
    page_id: Optional[str] = ""
    form_id: Optional[str] = ""
    platform: Optional[str] = ""
    assigned_to: Optional[str] = ""
    meta_created_time: Optional[str] = ""
    sync_status: Optional[str] = ""
    store_width: Optional[float] = None
    store_length: Optional[float] = None
    store_height: Optional[float] = None
    store_area: Optional[float] = None



class LeadUpdate(BaseModel):
    customer_name: Optional[str] = None
    phone: Optional[str] = None
    edited_by_id: Optional[str] = ""
    edited_by_name: Optional[str] = ""
    edited_by_role: Optional[str] = ""
    salesman_id: Optional[str] = None
    salesman_name: Optional[str] = None
    shop_name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    pincode: Optional[str] = None
    business_type: Optional[str] = None
    remarks: Optional[str] = None
    follow_up_date: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    photo: Optional[str] = None
    status: Optional[str] = None
    store_images_json: Optional[str] = None
    store_videos_json: Optional[str] = None
    lead_source: Optional[str] = None
    facebook_lead_id: Optional[str] = None
    campaign_id: Optional[str] = None
    campaign_name: Optional[str] = None
    adset_id: Optional[str] = None
    adset_name: Optional[str] = None
    ad_id: Optional[str] = None
    ad_name: Optional[str] = None
    page_id: Optional[str] = None
    form_id: Optional[str] = None
    platform: Optional[str] = None
    assigned_to: Optional[str] = None
    meta_created_time: Optional[str] = None
    sync_status: Optional[str] = None
    store_width: Optional[float] = None
    store_length: Optional[float] = None
    store_height: Optional[float] = None
    store_area: Optional[float] = None



class LeadOut(BaseModel):
    id: str
    lead_number: str
    salesman_id: str
    salesman_name: str
    customer_name: str
    phone: str
    shop_name: str
    address: str
    city: str
    pincode: str
    business_type: str
    remarks: str
    follow_up_date: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    photo: str
    status: str
    store_images_json: Optional[str] = "[]"
    store_videos_json: Optional[str] = "[]"
    lead_source: Optional[str] = ""
    facebook_lead_id: Optional[str] = ""
    campaign_id: Optional[str] = ""
    campaign_name: Optional[str] = ""
    adset_id: Optional[str] = ""
    adset_name: Optional[str] = ""
    ad_id: Optional[str] = ""
    ad_name: Optional[str] = ""
    page_id: Optional[str] = ""
    form_id: Optional[str] = ""
    platform: Optional[str] = ""
    assigned_to: Optional[str] = ""
    meta_created_time: Optional[str] = ""
    sync_status: Optional[str] = ""
    created_by: Optional[str] = ""
    current_owner: Optional[str] = ""
    last_updated_by: Optional[str] = ""
    created_note: Optional[str] = ""
    created_note_by: Optional[str] = ""
    created_note_date: Optional[str] = ""
    created_note_time: Optional[str] = ""
    created_at: int
    updated_at: Optional[int] = None
    store_width: Optional[float] = None
    store_length: Optional[float] = None
    store_height: Optional[float] = None
    store_area: Optional[float] = None


    model_config = {"from_attributes": True}


class LeadActivityOut(BaseModel):
    id: str
    lead_id: str
    lead_number: str
    date: str
    time: str
    username: str
    role: str
    action: str
    old_value: str
    new_value: str
    created_at: int

    model_config = {"from_attributes": True}


class FollowupCreate(BaseModel):
    lead_id: str
    priority: Optional[str] = "Medium"
    follow_up_date: str
    follow_up_time: Optional[str] = ""
    notes: Optional[str] = ""
    created_by_id: Optional[str] = ""
    created_by_name: Optional[str] = ""
    created_by: Optional[str] = ""
    created_role: Optional[str] = ""
    assigned_to: Optional[str] = ""


class FollowupUpdate(BaseModel):
    priority: Optional[str] = None
    follow_up_date: Optional[str] = None
    follow_up_time: Optional[str] = None
    status: Optional[str] = None # Pending | Completed | Missed | Cancelled
    notes: Optional[str] = None
    completed_by: Optional[str] = None
    completed_date: Optional[str] = None
    edited_by_name: Optional[str] = ""
    edited_by_role: Optional[str] = ""
    created_by_id: Optional[str] = None
    created_by_name: Optional[str] = None


class FollowupOut(BaseModel):
    id: str
    lead_id: str
    priority: str
    follow_up_date: str
    follow_up_time: str
    status: str
    notes: str
    created_by_id: str
    created_by_name: str
    created_by: str
    created_role: str
    assigned_to: str
    completed_date: str
    completed_at: int
    completed_by: str
    created_at: int
    updated_at: int

    # Flattened lead details
    customer_name: Optional[str] = ""
    phone: Optional[str] = ""
    shop_name: Optional[str] = ""
    business_type: Optional[str] = ""
    city: Optional[str] = ""
    lead_number: Optional[str] = ""
    lead_source: Optional[str] = ""
    salesman_name: Optional[str] = ""
    assigned_to: Optional[str] = "" # matching models.py
    lead_status: Optional[str] = ""

    model_config = {"from_attributes": True}


class FollowupHistoryOut(BaseModel):
    id: str
    followup_id: str
    lead_id: str
    old_date: str
    new_date: str
    old_time: str
    new_time: str
    old_status: str
    new_status: str
    user: str
    role: str
    timestamp: int
    changed_by: str
    changed_at: int
    date: str
    time: str

    model_config = {"from_attributes": True}


class NotificationOut(BaseModel):
    id: str
    user_id: Optional[str] = None
    role: Optional[str] = None
    message: str
    type: str
    lead_id: Optional[str] = None
    read: bool
    created_at: int

    model_config = {"from_attributes": True}


# ─── Settings schemas ─────────────────────────────────────────────────────────

class QuotationTermBase(BaseModel):
    text: str
    display_order: Optional[int] = 0
    is_enabled: Optional[bool] = True

class QuotationTermCreate(QuotationTermBase):
    pass

class QuotationTermUpdate(BaseModel):
    text: Optional[str] = None
    display_order: Optional[int] = None
    is_enabled: Optional[bool] = None

class QuotationTermOut(QuotationTermBase):
    id: str
    model_config = {"from_attributes": True}


class QuotationMaterialBase(BaseModel):
    text: str
    display_order: Optional[int] = 0
    is_enabled: Optional[bool] = True

class QuotationMaterialCreate(QuotationMaterialBase):
    pass

class QuotationMaterialUpdate(BaseModel):
    text: Optional[str] = None
    display_order: Optional[int] = None
    is_enabled: Optional[bool] = None

class QuotationMaterialOut(QuotationMaterialBase):
    id: str
    model_config = {"from_attributes": True}


class QuotationBankBase(BaseModel):
    bank_name: str
    account_holder: str
    account_number: str
    ifsc_code: str
    branch: Optional[str] = ""
    display_order: Optional[int] = 0
    is_enabled: Optional[bool] = True

class QuotationBankCreate(QuotationBankBase):
    pass

class QuotationBankUpdate(BaseModel):
    bank_name: Optional[str] = None
    account_holder: Optional[str] = None
    account_number: Optional[str] = None
    ifsc_code: Optional[str] = None
    branch: Optional[str] = None
    display_order: Optional[int] = None
    is_enabled: Optional[bool] = None

class QuotationBankOut(QuotationBankBase):
    id: str
    model_config = {"from_attributes": True}


class QuotationSocialBase(BaseModel):
    platform: str
    icon: Optional[str] = ""
    qr_code_url: Optional[str] = ""
    cta_text: Optional[str] = ""
    display_order: Optional[int] = 0
    is_enabled: Optional[bool] = True

class QuotationSocialCreate(QuotationSocialBase):
    pass

class QuotationSocialUpdate(BaseModel):
    platform: Optional[str] = None
    icon: Optional[str] = None
    qr_code_url: Optional[str] = None
    cta_text: Optional[str] = None
    display_order: Optional[int] = None
    is_enabled: Optional[bool] = None

class QuotationSocialOut(QuotationSocialBase):
    id: str
    model_config = {"from_attributes": True}


class QuotationWhyChooseBase(BaseModel):
    text: str
    display_order: Optional[int] = 0
    is_enabled: Optional[bool] = True

class QuotationWhyChooseCreate(QuotationWhyChooseBase):
    pass

class QuotationWhyChooseUpdate(BaseModel):
    text: Optional[str] = None
    display_order: Optional[int] = None
    is_enabled: Optional[bool] = None

class QuotationWhyChooseOut(QuotationWhyChooseBase):
    id: str
    model_config = {"from_attributes": True}


class QuotationServiceBase(BaseModel):
    name: str
    display_order: Optional[int] = 0
    is_enabled: Optional[bool] = True

class QuotationServiceCreate(QuotationServiceBase):
    pass

class QuotationServiceUpdate(BaseModel):
    name: Optional[str] = None
    display_order: Optional[int] = None
    is_enabled: Optional[bool] = None

class QuotationServiceOut(QuotationServiceBase):
    id: str
    model_config = {"from_attributes": True}


class QuotationFooterBase(BaseModel):
    text: str
    display_order: Optional[int] = 0
    is_enabled: Optional[bool] = True

class QuotationFooterCreate(QuotationFooterBase):
    pass

class QuotationFooterUpdate(BaseModel):
    text: Optional[str] = None
    display_order: Optional[int] = None
    is_enabled: Optional[bool] = None

class QuotationFooterOut(QuotationFooterBase):
    id: str
    model_config = {"from_attributes": True}


# ─── MANUFACTURING & PRODUCTION SCHEMAS ─────────────────────────────────────

class ProductionItemBase(BaseModel):
    product_name: str
    product_description: Optional[str] = ""
    hsn: Optional[str] = ""
    quantity: float = 1.0
    unit: Optional[str] = "Pcs"
    product_image: Optional[str] = ""
    remarks: Optional[str] = ""

class ProductionItemOut(ProductionItemBase):
    id: str
    production_order_id: str
    product_id: Optional[str] = None
    model_config = {"from_attributes": True}

class ProductionWorkerBase(BaseModel):
    worker_name: str
    role: str

class ProductionWorkerCreate(ProductionWorkerBase):
    pass

class ProductionWorkerOut(ProductionWorkerBase):
    id: str
    production_order_id: str
    assigned_at: int
    assigned_by: str
    model_config = {"from_attributes": True}

class ProductionStageAction(BaseModel):
    stage_name: str
    action: str  # start | pause | resume | complete | skip
    completed_by: Optional[str] = ""
    remarks: Optional[str] = ""

class ProductionStatusHistoryOut(BaseModel):
    id: str
    production_order_id: str
    stage_name: str
    status: str
    start_time: int
    end_time: int
    completed_by: str
    remarks: str
    created_at: int
    model_config = {"from_attributes": True}

class ProductionNoteCreate(BaseModel):
    author: Optional[str] = "Factory Staff"
    note: str

class ProductionNoteOut(BaseModel):
    id: str
    production_order_id: str
    author: str
    note: str
    created_at: int
    model_config = {"from_attributes": True}

class ProductionAttachmentCreate(BaseModel):
    file_name: str
    file_type: Optional[str] = "General"
    file_url: str

class ProductionAttachmentOut(ProductionAttachmentCreate):
    id: str
    production_order_id: str
    uploaded_at: int
    model_config = {"from_attributes": True}

class ProductionOrderPriorityUpdate(BaseModel):
    priority: str  # Low | Medium | High | Urgent

class ProductionOrderOut(BaseModel):
    id: str
    production_number: str
    quotation_id: str
    quote_number: str
    customer_id: Optional[str] = None
    customer_name: str
    mobile: Optional[str] = ""
    address: Optional[str] = ""
    payment_status: str
    priority: str
    order_date: int
    expected_dispatch: Optional[str] = ""
    sales_person: Optional[str] = ""
    status: str
    current_stage: str
    customer_notes: Optional[str] = ""
    quotation_remarks: Optional[str] = ""
    sales_instructions: Optional[str] = ""
    created_at: int
    updated_at: int
    items: Optional[List[ProductionItemOut]] = []
    workers: Optional[List[ProductionWorkerOut]] = []
    stages: Optional[List[ProductionStatusHistoryOut]] = []
    notes: Optional[List[ProductionNoteOut]] = []
    attachments: Optional[List[ProductionAttachmentOut]] = []
    material_requirements: Optional[List['ProductionMaterialRequirementOut']] = []
    model_config = {"from_attributes": True}

class ProductionDashboardKPIs(BaseModel):
    total_orders: int
    accepted: int
    started: int
    processing: int
    completed: int
    today_orders: Optional[int] = 0
    late_orders: Optional[int] = 0
    # Backward compatibility aliases
    accepted_orders: Optional[int] = 0
    started_orders: Optional[int] = 0
    processing_orders: Optional[int] = 0
    completed_orders: Optional[int] = 0

# ─── INVENTORY & RAW MATERIAL SCHEMAS ───────────────────────────────────────

class RawMaterialBase(BaseModel):
    material_code: str
    name: str
    category: Optional[str] = "General"
    unit: Optional[str] = "Pcs"
    current_stock: float = 0.0
    reserved_stock: float = 0.0
    minimum_level: float = 10.0
    reorder_quantity: float = 50.0
    unit_cost: float = 0.0
    location: Optional[str] = "Main Factory Warehouse"

class RawMaterialCreate(RawMaterialBase):
    pass

class RawMaterialUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    unit: Optional[str] = None
    current_stock: Optional[float] = None
    minimum_level: Optional[float] = None
    reorder_quantity: Optional[float] = None
    unit_cost: Optional[float] = None
    location: Optional[str] = None

class RawMaterialOut(RawMaterialBase):
    id: str
    created_at: int
    updated_at: int
    available_stock: Optional[float] = 0.0
    is_low_stock: Optional[bool] = False
    model_config = {"from_attributes": True}

class ProductionMaterialRequirementOut(BaseModel):
    id: str
    production_order_id: str
    material_id: str
    material_name: str
    material_description: Optional[str] = ""
    required_qty: float
    reserved_qty: float
    deducted_qty: float
    unit: str
    status: str  # Inventory allocation status: Reserved | Issued | Insufficient
    # Manufacturing progress (separate from inventory)
    prepared_qty: float = 0.0
    manufacturing_status: str = "Pending"  # Pending | In Progress | Completed
    created_at: int
    model_config = {"from_attributes": True}

    @computed_field
    @property
    def remaining_qty(self) -> float:
        return max(0.0, float(self.required_qty or 0.0) - float(self.prepared_qty or 0.0))


class MaterialProgressUpdate(BaseModel):
    """Input schema for factory worker material progress updates."""
    prepared_qty: float

    @field_validator("prepared_qty")
    @classmethod
    def validate_prepared_qty(cls, v):
        if v < 0:
            raise ValueError("prepared_qty must be non-negative")
        return v

class InventoryTransactionOut(BaseModel):
    id: str
    material_id: str
    material_name: str
    type: str
    qty: float
    reference_id: str
    remarks: str
    created_by: str
    created_at: int
    model_config = {"from_attributes": True}

class PurchaseRequestCreate(BaseModel):
    material_id: str
    requested_qty: float
    reason: Optional[str] = ""

class PurchaseRequestOut(BaseModel):
    id: str
    request_number: str
    production_order_id: Optional[str] = ""
    material_id: str
    material_name: str
    requested_qty: float
    unit: str
    status: str
    reason: str
    created_by: str
    created_at: int
    model_config = {"from_attributes": True}


