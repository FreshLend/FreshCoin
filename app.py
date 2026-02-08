import os
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_babel import Babel, _, get_locale
from werkzeug.security import generate_password_hash, check_password_hash
from PIL import Image, ImageDraw
import random
import string
from datetime import datetime
import io
import math

SYSTEM_ID = "000000000000000000213"
SYSTEM_USERNAME = "FreshGame"
SYSTEM_DISPLAY_NAME = ""
SYSTEM_EMAIL = "freshlend.studio@gmail.com"
SYSTEM_PASSWORD = "000213"
SYSTEM_BALANCE = 1000.0

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///bank.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['BABEL_DEFAULT_LOCALE'] = 'en'
app.config['BABEL_TRANSLATION_DIRECTORIES'] = 'translations'

db = SQLAlchemy(app)
babel = Babel(app)

def get_locale():
    if 'user_id' in session:
        user = db.session.get(User, session['user_id'])
        if user and hasattr(user, 'language'):
            return user.language
    
    language = request.args.get('lang')
    if language in ['en', 'ru']:
        return language
    
    return request.accept_languages.best_match(['en', 'ru']) or 'en'

babel.init_app(app, locale_selector=get_locale)

@app.template_filter('avatar_url')
def avatar_url_filter(avatar_path):
    if avatar_path:
        return url_for('static', filename=avatar_path)
    return url_for('static', filename='default_avatar.webp')

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(21), unique=True, nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    display_name = db.Column(db.String(100))
    avatar_path = db.Column(db.String(200))
    balance = db.Column(db.Float, default=0.0)
    last_ad_watch = db.Column(db.DateTime, default=datetime.min)
    ad_count_today = db.Column(db.Integer, default=0)
    last_login = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_username_change = db.Column(db.DateTime, default=datetime.utcnow)
    language = db.Column(db.String(5), default='en')
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Currency(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    symbol = db.Column(db.String(10), unique=True, nullable=False)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    total_supply = db.Column(db.Float, default=1000000000.0)
    reserve_fc = db.Column(db.Float, default=10000.0)
    reserve_currency = db.Column(db.Float, default=0.0)
    commission_rate = db.Column(db.Float, default=0.025)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    
    creator = db.relationship('User', backref=db.backref('created_currencies', lazy=True))
    
    @property
    def current_price(self):
        if self.reserve_currency == 0:
            return 0.000000001
        return self.reserve_fc / self.reserve_currency
    
    @property
    def liquidity(self):
        return self.reserve_fc * 2

class Wallet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    currency_id = db.Column(db.Integer, db.ForeignKey('currency.id'), nullable=False)
    balance = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('wallets', lazy=True))
    currency = db.relationship('Currency', backref=db.backref('wallets', lazy=True))
    
    __table_args__ = (db.UniqueConstraint('user_id', 'currency_id'),)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    transaction_type = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(200))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('transactions', lazy=True))

class ExchangeTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    from_currency = db.Column(db.String(10), nullable=False)
    to_currency = db.Column(db.String(10), nullable=False)
    from_amount = db.Column(db.Float, nullable=False)
    to_amount = db.Column(db.Float, nullable=False)
    price = db.Column(db.Float, nullable=False)
    commission = db.Column(db.Float, default=0.0)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('exchange_transactions', lazy=True))

class ExchangeSystem:
    @staticmethod
    def calculate_buy_amount(currency, fc_amount):
        if currency.reserve_fc <= 0 or currency.reserve_currency <= 0:
            return 0
        
        commission_rate = currency.commission_rate
        net_fc_amount = fc_amount * (1 - commission_rate)
        
        k = currency.reserve_fc * currency.reserve_currency
        new_reserve_fc = currency.reserve_fc + net_fc_amount
        new_reserve_currency = k / new_reserve_fc
        currency_amount = currency.reserve_currency - new_reserve_currency
        
        price_impact = abs((currency_amount / currency.reserve_currency) * 100)
        if price_impact > 50:
            raise ValueError("Price impact too high (max 50%)")
        
        return max(0, currency_amount)
    
    @staticmethod
    def calculate_sell_amount(currency, currency_amount):
        if currency.reserve_fc <= 0 or currency.reserve_currency <= 0:
            return 0
        
        commission_rate = currency.commission_rate
        net_currency_amount = currency_amount * (1 - commission_rate)
        
        k = currency.reserve_fc * currency.reserve_currency
        new_reserve_currency = currency.reserve_currency + net_currency_amount
        new_reserve_fc = k / new_reserve_currency
        fc_amount = currency.reserve_fc - new_reserve_fc
        
        price_impact = abs((fc_amount / currency.reserve_fc) * 100)
        if price_impact > 50:
            raise ValueError("Price impact too high (max 50%)")
        
        return max(0, fc_amount)
    
    @staticmethod
    def get_price_impact(currency, amount, is_buy=True):
        if is_buy:
            if currency.reserve_fc <= 0:
                return 0
            new_reserve_fc = currency.reserve_fc + amount
            new_reserve_currency = (currency.reserve_fc * currency.reserve_currency) / new_reserve_fc
            new_price = new_reserve_fc / new_reserve_currency
        else:
            if currency.reserve_currency <= 0:
                return 0
            new_reserve_currency = currency.reserve_currency + amount
            new_reserve_fc = (currency.reserve_fc * currency.reserve_currency) / new_reserve_currency
            new_price = new_reserve_fc / new_reserve_currency
        
        old_price = currency.current_price
        return abs((new_price - old_price) / old_price * 100)

def transfer_funds(sender_id, recipient_identifier, amount, currency_symbol='FC'):
    sender = db.session.get(User, sender_id)
    if not sender:
        return {'success': False, 'message': 'Sender not found'}
    
    if currency_symbol == 'FC':
        if sender.balance < amount:
            return {'success': False, 'message': 'Insufficient funds'}
        
        recipient = User.query.filter((User.username == recipient_identifier) | (User.user_id == recipient_identifier)).first()
        if not recipient:
            return {'success': False, 'message': 'Recipient not found'}
        
        if sender.id == recipient.id:
            return {'success': False, 'message': 'Cannot transfer to yourself'}
        
        commission = amount * 0.05
        net_amount = amount - commission
        
        system_user = User.query.filter_by(user_id=SYSTEM_ID).first()
        if not system_user:
            return {'success': False, 'message': 'System account not found'}
        
        sender.balance -= amount
        recipient.balance += net_amount
        system_user.balance += commission
        
        sender_transaction = Transaction(
            user_id=sender.id,
            amount=amount,
            transaction_type='debit',
            description=f'Transfer {currency_symbol} to {recipient.username} (commission: {commission:.2f} {currency_symbol})'
        )
        
        recipient_transaction = Transaction(
            user_id=recipient.id,
            amount=net_amount,
            transaction_type='credit',
            description=f'Transfer {currency_symbol} from {sender.username}'
        )
        
        system_transaction = Transaction(
            user_id=system_user.id,
            amount=commission,
            transaction_type='credit',
            description=f'Commission from {currency_symbol} transfer'
        )
        
        db.session.add(sender_transaction)
        db.session.add(recipient_transaction)
        db.session.add(system_transaction)
        db.session.commit()
        
        return {'success': True, 'message': f'Transferred {net_amount:.2f} {currency_symbol} to {recipient.username}'}
    
    else:
        currency = Currency.query.filter_by(symbol=currency_symbol).first()
        if not currency:
            return {'success': False, 'message': 'Currency not found'}
        
        sender_wallet = Wallet.query.filter_by(user_id=sender.id, currency_id=currency.id).first()
        if not sender_wallet or sender_wallet.balance < amount:
            return {'success': False, 'message': 'Insufficient funds in specified currency'}
        
        recipient = User.query.filter((User.username == recipient_identifier) | (User.user_id == recipient_identifier)).first()
        if not recipient:
            return {'success': False, 'message': 'Recipient not found'}
        
        if sender.id == recipient.id:
            return {'success': False, 'message': 'Cannot transfer to yourself'}
        
        commission = amount * 0.05
        net_amount = amount - commission
        
        system_user = User.query.filter_by(user_id=SYSTEM_ID).first()
        if not system_user:
            return {'success': False, 'message': 'System account not found'}
        
        recipient_wallet = Wallet.query.filter_by(user_id=recipient.id, currency_id=currency.id).first()
        if not recipient_wallet:
            recipient_wallet = Wallet(user_id=recipient.id, currency_id=currency.id, balance=net_amount)
            db.session.add(recipient_wallet)
        else:
            recipient_wallet.balance += net_amount
        
        sender_wallet.balance -= amount
        
        creator_wallet = Wallet.query.filter_by(user_id=currency.creator_id, currency_id=currency.id).first()
        if not creator_wallet:
            creator_wallet = Wallet(user_id=currency.creator_id, currency_id=currency.id, balance=commission)
            db.session.add(creator_wallet)
        else:
            creator_wallet.balance += commission
        
        system_commission_main = commission * currency.current_price
        system_user.balance += system_commission_main
        
        sender_transaction = Transaction(
            user_id=sender.id,
            amount=amount,
            transaction_type='debit',
            description=f'Transfer {currency_symbol} to {recipient.username}'
        )
        
        db.session.add(sender_transaction)
        db.session.commit()
        
        return {'success': True, 'message': f'Transferred {net_amount:.4f} {currency_symbol} to {recipient.username}'}

def create_currency(user_id, name, symbol, commission_rate_percent):
    user = db.session.get(User, user_id)
    if not user:
        return {'success': False, 'message': 'User not found'}
    
    if user.balance < 1000:
        return {'success': False, 'message': 'Insufficient funds to create currency (requires 1000 FC)'}
    
    existing_currency = Currency.query.filter((Currency.name == name) | (Currency.symbol == symbol)).first()
    if existing_currency:
        return {'success': False, 'message': 'Currency name or symbol already exists'}
    
    commission_rate = commission_rate_percent / 100
    
    if commission_rate_percent < 0.5 or commission_rate_percent > 25:
        return {'success': False, 'message': 'Commission rate must be between 0.5% and 25%'}
    
    user.balance -= 1000
    
    initial_fc_reserve = 1000.0
    initial_currency_reserve = 100000000.0
    
    currency = Currency(
        name=name,
        symbol=symbol,
        creator_id=user.id,
        reserve_fc=initial_fc_reserve,
        reserve_currency=initial_currency_reserve,
        commission_rate=commission_rate
    )
    
    db.session.add(currency)
    db.session.flush()
    
    creator_wallet = Wallet(
        user_id=user.id,
        currency_id=currency.id,
        balance=initial_currency_reserve
    )
    
    db.session.add(creator_wallet)
    
    transaction = Transaction(
        user_id=user.id,
        amount=1000,
        transaction_type='debit',
        description=f'Fee for creating currency {name}'
    )
    
    db.session.add(transaction)
    db.session.commit()
    
    return {'success': True, 'message': f'Currency {name} ({symbol}) created successfully!', 'currency_id': currency.id}

def exchange_currency(user_id, from_currency_symbol, to_currency_symbol, amount):
    user = db.session.get(User, user_id)
    if not user:
        return {'success': False, 'message': 'User not found'}
    
    if amount <= 0:
        return {'success': False, 'message': 'Amount must be positive'}
    
    if from_currency_symbol == to_currency_symbol:
        return {'success': False, 'message': 'Cannot exchange currency for itself'}
    
    try:
        if from_currency_symbol == 'FC':
            to_currency = Currency.query.filter_by(symbol=to_currency_symbol).first()
            if not to_currency:
                return {'success': False, 'message': 'Target currency not found'}
            
            if user.balance < amount:
                return {'success': False, 'message': 'Insufficient FC balance'}
            
            currency_amount = ExchangeSystem.calculate_buy_amount(to_currency, amount)
            
            if currency_amount <= 0:
                return {'success': False, 'message': 'Insufficient liquidity'}
            
            price_impact = ExchangeSystem.get_price_impact(to_currency, amount, is_buy=True)
            
            if price_impact > 50:
                return {'success': False, 'message': f'Price impact too high ({price_impact:.1f}%). Try smaller amount.'}
            
            commission_rate = to_currency.commission_rate
            commission_fc = amount * commission_rate
            net_fc_amount = amount - commission_fc
            
            to_currency.reserve_fc += net_fc_amount
            to_currency.reserve_currency -= currency_amount
            
            user.balance -= amount
            
            wallet = Wallet.query.filter_by(user_id=user.id, currency_id=to_currency.id).first()
            if not wallet:
                wallet = Wallet(user_id=user.id, currency_id=to_currency.id, balance=currency_amount)
                db.session.add(wallet)
            else:
                wallet.balance += currency_amount
            
            creator = User.query.get(to_currency.creator_id)
            if creator:
                creator.balance += commission_fc
            
            exchange_tx = ExchangeTransaction(
                user_id=user.id,
                from_currency='FC',
                to_currency=to_currency_symbol,
                from_amount=amount,
                to_amount=currency_amount,
                price=amount / currency_amount,
                commission=commission_fc
            )
            db.session.add(exchange_tx)
            
            db.session.commit()
            
            return {
                'success': True, 
                'message': f'Bought {currency_amount:.4f} {to_currency_symbol} for {amount:.2f} FC',
                'received': currency_amount,
                'price': amount / currency_amount,
                'price_impact': f'{price_impact:.2f}%'
            }
        
        elif to_currency_symbol == 'FC':
            from_currency = Currency.query.filter_by(symbol=from_currency_symbol).first()
            if not from_currency:
                return {'success': False, 'message': 'Source currency not found'}
            
            wallet = Wallet.query.filter_by(user_id=user.id, currency_id=from_currency.id).first()
            if not wallet or wallet.balance < amount:
                return {'success': False, 'message': 'Insufficient currency balance'}
            
            fc_amount = ExchangeSystem.calculate_sell_amount(from_currency, amount)
            
            if fc_amount <= 0:
                return {'success': False, 'message': 'Insufficient liquidity'}
            
            price_impact = ExchangeSystem.get_price_impact(from_currency, amount, is_buy=False)
            
            if price_impact > 50:
                return {'success': False, 'message': f'Price impact too high ({price_impact:.1f}%). Try smaller amount.'}
            
            commission_rate = from_currency.commission_rate
            commission_currency = amount * commission_rate
            net_currency_amount = amount - commission_currency
            
            from_currency.reserve_currency += net_currency_amount
            from_currency.reserve_fc -= fc_amount
            
            wallet.balance -= amount
            user.balance += fc_amount
            
            creator_wallet = Wallet.query.filter_by(user_id=from_currency.creator_id, currency_id=from_currency.id).first()
            if not creator_wallet:
                creator_wallet = Wallet(user_id=from_currency.creator_id, currency_id=from_currency.id, balance=commission_currency)
                db.session.add(creator_wallet)
            else:
                creator_wallet.balance += commission_currency
            
            exchange_tx = ExchangeTransaction(
                user_id=user.id,
                from_currency=from_currency_symbol,
                to_currency='FC',
                from_amount=amount,
                to_amount=fc_amount,
                price=fc_amount / amount,
                commission=commission_currency
            )
            db.session.add(exchange_tx)
            
            db.session.commit()
            
            return {
                'success': True, 
                'message': f'Sold {amount:.4f} {from_currency_symbol} for {fc_amount:.2f} FC',
                'received': fc_amount,
                'price': fc_amount / amount,
                'price_impact': f'{price_impact:.2f}%'
            }
        
        else:
            from_currency = Currency.query.filter_by(symbol=from_currency_symbol).first()
            to_currency = Currency.query.filter_by(symbol=to_currency_symbol).first()
            
            if not from_currency or not to_currency:
                return {'success': False, 'message': 'Currency not found'}
            
            from_wallet = Wallet.query.filter_by(user_id=user.id, currency_id=from_currency.id).first()
            if not from_wallet or from_wallet.balance < amount:
                return {'success': False, 'message': 'Insufficient currency balance'}
            
            fc_amount = ExchangeSystem.calculate_sell_amount(from_currency, amount)
            
            if fc_amount <= 0:
                return {'success': False, 'message': 'Insufficient liquidity in source currency'}
            
            currency_amount = ExchangeSystem.calculate_buy_amount(to_currency, fc_amount)
            
            if currency_amount <= 0:
                return {'success': False, 'message': 'Insufficient liquidity in target currency'}
            
            price_impact_sell = ExchangeSystem.get_price_impact(from_currency, amount, is_buy=False)
            price_impact_buy = ExchangeSystem.get_price_impact(to_currency, fc_amount, is_buy=True)
            
            if price_impact_sell > 50 or price_impact_buy > 50:
                return {'success': False, 'message': 'Price impact too high. Try smaller amount.'}
            
            commission_rate_sell = from_currency.commission_rate
            commission_sell = amount * commission_rate_sell
            net_sell_amount = amount - commission_sell
            
            from_currency.reserve_currency += net_sell_amount
            from_currency.reserve_fc -= fc_amount
            
            commission_rate_buy = to_currency.commission_rate
            commission_buy = fc_amount * commission_rate_buy
            net_fc_amount = fc_amount - commission_buy
            
            to_currency.reserve_fc += net_fc_amount
            to_currency.reserve_currency -= currency_amount
            
            from_wallet.balance -= amount
            
            to_wallet = Wallet.query.filter_by(user_id=user.id, currency_id=to_currency.id).first()
            if not to_wallet:
                to_wallet = Wallet(user_id=user.id, currency_id=to_currency.id, balance=currency_amount)
                db.session.add(to_wallet)
            else:
                to_wallet.balance += currency_amount
            
            from_creator_wallet = Wallet.query.filter_by(user_id=from_currency.creator_id, currency_id=from_currency.id).first()
            if not from_creator_wallet:
                from_creator_wallet = Wallet(user_id=from_currency.creator_id, currency_id=from_currency.id, balance=commission_sell)
                db.session.add(from_creator_wallet)
            else:
                from_creator_wallet.balance += commission_sell
            
            to_creator = User.query.get(to_currency.creator_id)
            if to_creator:
                to_creator.balance += commission_buy
            
            exchange_tx = ExchangeTransaction(
                user_id=user.id,
                from_currency=from_currency_symbol,
                to_currency=to_currency_symbol,
                from_amount=amount,
                to_amount=currency_amount,
                price=currency_amount / amount,
                commission=commission_sell + commission_buy
            )
            db.session.add(exchange_tx)
            
            db.session.commit()
            
            return {
                'success': True, 
                'message': f'Exchanged {amount:.4f} {from_currency_symbol} to {currency_amount:.4f} {to_currency_symbol}',
                'received': currency_amount,
                'price': currency_amount / amount,
                'price_impact': f'{(price_impact_sell + price_impact_buy)/2:.2f}%'
            }
    
    except ValueError as e:
        return {'success': False, 'message': str(e)}
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'message': f'Exchange failed: {str(e)}'}

def get_max_buy_amount(currency_symbol):
    if currency_symbol == 'FC':
        return {'success': False, 'message': 'Cannot buy FC with FC'}
    
    currency = Currency.query.filter_by(symbol=currency_symbol).first()
    if not currency:
        return {'success': False, 'message': 'Currency not found'}
    
    x = currency.reserve_fc
    y = currency.reserve_currency
    k = x * y
    
    max_price_increase = 0.5
    target_price = currency.current_price * (1 + max_price_increase)

    new_x = math.sqrt(k * target_price)
    new_y = math.sqrt(k / target_price)
    
    max_fc_amount = new_x - x
    
    return {
        'success': True,
        'max_amount': max_fc_amount,
        'price_impact': '50%',
        'current_price': currency.current_price,
        'estimated_price': target_price
    }

def get_max_sell_amount(currency_symbol, user_id):
    if currency_symbol == 'FC':
        return {'success': False, 'message': 'Cannot sell FC'}
    
    currency = Currency.query.filter_by(symbol=currency_symbol).first()
    if not currency:
        return {'success': False, 'message': 'Currency not found'}
    
    wallet = Wallet.query.filter_by(user_id=user_id, currency_id=currency.id).first()
    user_balance = wallet.balance if wallet else 0
    
    x = currency.reserve_fc
    y = currency.reserve_currency
    k = x * y
    
    max_price_decrease = 0.5
    target_price = currency.current_price * (1 - max_price_decrease)
    
    new_x = math.sqrt(k * target_price)
    new_y = math.sqrt(k / target_price)
    
    max_currency_amount = new_y - y
    
    max_sell = min(user_balance, max_currency_amount)
    
    return {
        'success': True,
        'max_amount': max_sell,
        'user_balance': user_balance,
        'price_impact': '50%',
        'current_price': currency.current_price,
        'estimated_price': target_price
    }

def generate_avatar(user_id):
    width, height = 128, 128
    
    r1, g1, b1 = [random.randint(0, 255) for _ in range(3)]
    r2, g2, b2 = [random.randint(0, 255) for _ in range(3)]
    
    img = Image.new('RGB', (width, height))
    draw = ImageDraw.Draw(img)
    
    for y in range(height):
        r = int(r1 + (r2 - r1) * y / height)
        g = int(g1 + (g2 - g1) * y / height)
        b = int(b1 + (b2 - b1) * y / height)
        
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    
    if user_id:
        draw.text((width//2, height//2), user_id[0].upper(), fill='white')
    
    buffer = io.BytesIO()
    img.save(buffer, format='WEBP')
    buffer.seek(0)
    
    if not os.path.exists('static'):
        os.makedirs('static')
    
    avatar_filename = f'avatar_{user_id}.webp'
    avatar_path = os.path.join('static', avatar_filename)
    
    with open(avatar_path, 'wb') as f:
        f.write(buffer.getvalue())
    
    return avatar_filename

def can_watch_ad(user):
    today = datetime.now().date()
    last_ad_date = user.last_ad_watch.date() if user.last_ad_watch else None
    
    if last_ad_date != today:
        user.ad_count_today = 0
        db.session.commit()
        return True
    
    return user.ad_count_today < 100

def watch_ad(user):
    if not can_watch_ad(user):
        return {'success': False, 'message': 'Daily ad limit reached'}
    
    reward = round(random.uniform(0.1, 1.0), 2)
    
    user.balance += reward
    user.ad_count_today += 1
    user.last_ad_watch = datetime.now()
    
    transaction = Transaction(
        user_id=user.id,
        amount=reward,
        transaction_type='credit',
        description=f'Ad reward #{user.ad_count_today}'
    )
    
    db.session.add(transaction)
    db.session.commit()
    
    return {'success': True, 'reward': reward, 'balance': user.balance}

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user = db.session.get(User, session['user_id'])
    if not user:
        return redirect(url_for('login'))
    
    can_watch = can_watch_ad(user)
    remaining_ads = max(0, 100 - user.ad_count_today)
    
    return render_template('index.html', user=user, can_watch=can_watch, remaining_ads=remaining_ads)

def generate_user_id():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=21))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        
        if len(password) < 6:
            flash(_('Password must be at least 6 characters long'), 'error')
            return render_template('register.html')
        
        if password != confirm_password:
            flash(_('Passwords do not match'), 'error')
            return render_template('register.html')
        
        if User.query.filter_by(username=username).first():
            flash(_('Username already exists'), 'error')
            return render_template('register.html')
        
        if User.query.filter_by(email=email).first():
            flash(_('Email already registered'), 'error')
            return render_template('register.html')
        
        user_id = generate_user_id()
        hashed_password = generate_password_hash(password)
        user = User(user_id=user_id, username=username, email=email, password_hash=hashed_password)
        user.avatar_path = generate_avatar(user_id)
        
        db.session.add(user)
        db.session.commit()
        
        flash(_('Registration successful!'), 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login_input = request.form['login']
        password = request.form['password']
        
        user = User.query.filter((User.username == login_input) | (User.email == login_input)).first()
        
        if user and user.check_password(password):
            session['user_id'] = user.id
            user.last_login = datetime.now()
            db.session.commit()
            return redirect(url_for('index'))
        else:
            flash(_('Invalid credentials'), 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

@app.route('/watch-ad', methods=['POST'])
def watch_ad_route():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'})
    
    user = db.session.get(User, session['user_id'])
    if not user:
        return jsonify({'success': False, 'message': 'User not found'})
    
    result = watch_ad(user)
    return jsonify(result)

def process_avatar_upload(file, user_id):
    if not file:
        return None
    
    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    filename = file.filename
    if '.' in filename and filename.rsplit('.', 1)[1].lower() not in allowed_extensions:
        return None
    
    try:
        img = Image.open(file.stream)

        img = img.resize((256, 256), Image.Resampling.LANCZOS)
        
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        avatar_filename = f'avatar_{user_id}.webp'
        avatar_path = os.path.join('static', avatar_filename)
        
        img.save(avatar_path, 'WEBP', quality=85)
        
        return avatar_filename
    except Exception as e:
        print(f"Error processing avatar: {e}")
        return None

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user = db.session.get(User, session['user_id'])
    if not user:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'change_display_name':
            display_name = request.form.get('display_name', '').strip()
            if display_name:
                user.display_name = display_name
            else:
                user.display_name = None
            
            db.session.commit()
            flash(_('Display name updated'), 'success')
        
        elif action == 'change_username':
            new_username = request.form.get('username', '').strip()
            
            if User.query.filter(User.username == new_username, User.id != user.id).first():
                flash(_('Username already taken'), 'error')
            else:
                time_since_last_change = datetime.utcnow() - user.last_username_change
                days_since_last_change = time_since_last_change.days
                
                if days_since_last_change < 7:
                    days_remaining = 7 - days_since_last_change
                    flash(_('Username can only be changed once per week. Please wait {days_remaining} more day(s).').format(days_remaining=days_remaining), 'error')
                else:
                    user.username = new_username
                    user.last_username_change = datetime.utcnow()
                    db.session.commit()
                    flash(_('Username updated successfully!'), 'success')
        
        elif action == 'change_password':
            current_password = request.form.get('current_password')
            new_password = request.form.get('new_password')
            confirm_new_password = request.form.get('confirm_new_password')
            
            if not user.check_password(current_password):
                flash(_('Current password is incorrect'), 'error')
            elif new_password != confirm_new_password:
                flash(_('New passwords do not match'), 'error')
            elif len(new_password) < 6:
                flash(_('Password must be at least 6 characters long'), 'error')
            else:
                user.password_hash = generate_password_hash(new_password)
                db.session.commit()
                flash(_('Password updated'), 'success')
        
        elif action == 'upload_avatar':
            if 'avatar' in request.files:
                file = request.files['avatar']
                if file.filename != '':
                    new_avatar_path = process_avatar_upload(file, user.user_id)
                    if new_avatar_path:
                        user.avatar_path = new_avatar_path
                        db.session.commit()
                        flash(_('Avatar updated successfully!'), 'success')
                    else:
                        flash(_('Invalid image file. Please upload a valid image (PNG, JPG, GIF, WEBP).'), 'error')
            else:
                flash(_('No file selected'), 'error')

    return render_template('settings.html', user=user)

@app.route('/change_language', methods=['POST'])
def change_language():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user = db.session.get(User, session['user_id'])
    if not user:
        return redirect(url_for('login'))
    
    language = request.form.get('language')
    if language in ['en', 'ru']:
        user.language = language
        db.session.commit()
        flash(_('Language changed successfully!'), 'success')
    else:
        flash(_('Invalid language selection.'), 'error')
    
    return redirect(url_for('settings'))

@app.route('/transfer', methods=['POST'])
def transfer_route():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'})
    
    sender_id = session['user_id']
    recipient_identifier = request.form.get('recipient')
    amount_str = request.form.get('amount')
    currency_symbol = request.form.get('currency', 'FC')
    
    try:
        amount = float(amount_str)
        if amount <= 0:
            return jsonify({'success': False, 'message': 'Amount must be positive'})
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid amount'})
    
    result = transfer_funds(sender_id, recipient_identifier, amount, currency_symbol)
    return jsonify(result)

@app.route('/create_currency', methods=['POST'])
def create_currency_route():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'})
    
    user_id = session['user_id']
    name = request.form.get('name')
    symbol = request.form.get('symbol')
    commission_rate_str = request.form.get('commission_rate')
    
    try:
        commission_rate = float(commission_rate_str)
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid commission rate'})
    
    result = create_currency(user_id, name, symbol, commission_rate)
    return jsonify(result)

@app.route('/currencies')
def currencies():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user = db.session.get(User, session['user_id'])
    if not user:
        return redirect(url_for('login'))
    
    currencies = Currency.query.all()
    wallets = Wallet.query.filter_by(user_id=user.id).all()
    
    return render_template('currencies.html', user=user, currencies=currencies, wallets=wallets)

@app.route('/get_currency_price/<symbol>')
def get_currency_price(symbol):
    if symbol == 'FC':
        return jsonify({'success': True, 'price': 1.0})
    
    currency = Currency.query.filter_by(symbol=symbol).first()
    if currency:
        return jsonify({'success': True, 'price': currency.current_price})
    else:
        return jsonify({'success': False, 'message': 'Currency not found'})

@app.route('/get_currencies')
def get_currencies():
    currencies = Currency.query.all()
    currency_list = [{'name': curr.name, 'symbol': curr.symbol} for curr in currencies]
    currency_list.insert(0, {'name': 'FreshCoin', 'symbol': 'FC'})
    return jsonify(currency_list)

@app.route('/get_wallet_balance/<symbol>')
def get_wallet_balance(symbol):
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'})
    
    user_id = session['user_id']
    
    if symbol == 'FC':
        user = db.session.get(User, user_id)
        return jsonify({'success': True, 'balance': user.balance if user else 0})
    
    currency = Currency.query.filter_by(symbol=symbol).first()
    if not currency:
        return jsonify({'success': False, 'message': 'Currency not found'})
    
    wallet = Wallet.query.filter_by(user_id=user_id, currency_id=currency.id).first()
    if wallet:
        return jsonify({'success': True, 'balance': wallet.balance})
    else:
        return jsonify({'success': True, 'balance': 0})

@app.route('/get_currency_details/<symbol>')
def get_currency_details(symbol):
    if symbol == 'FC':
        return jsonify({
            'success': True,
            'commission_rate': 0.05,
            'current_price': 1.0,
            'total_supply': float('inf'),
            'liquidity': 0
        })
    
    currency = Currency.query.filter_by(symbol=symbol).first()
    if currency:
        return jsonify({
            'success': True,
            'commission_rate': currency.commission_rate,
            'current_price': currency.current_price,
            'total_supply': currency.total_supply,
            'liquidity': currency.liquidity,
            'reserve_fc': currency.reserve_fc,
            'reserve_currency': currency.reserve_currency
        })
    else:
        return jsonify({'success': False, 'message': 'Currency not found'})

@app.route('/get_user_balance')
def get_user_balance():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'})
    
    user_id = session['user_id']
    user = db.session.get(User, user_id)
    if user:
        return jsonify({'success': True, 'balance': user.balance})
    else:
        return jsonify({'success': False, 'message': 'User not found'})

@app.route('/exchange', methods=['POST'])
def exchange_route():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'})
    
    user_id = session['user_id']
    from_currency = request.form.get('from_currency')
    to_currency = request.form.get('to_currency')
    amount_str = request.form.get('amount')
    
    try:
        amount = float(amount_str)
        if amount <= 0:
            return jsonify({'success': False, 'message': 'Amount must be positive'})
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid amount'})
    
    result = exchange_currency(user_id, from_currency, to_currency, amount)
    return jsonify(result)

@app.route('/get_max_buy/<symbol>')
def get_max_buy_route(symbol):
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'})
    
    user_id = session['user_id']
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'success': False, 'message': 'User not found'})
    
    result = get_max_buy_amount(symbol)
    
    if result['success']:
        result['user_fc_balance'] = user.balance
        result['affordable_max'] = min(result['max_amount'], user.balance)
    
    return jsonify(result)

@app.route('/get_max_sell/<symbol>')
def get_max_sell_route(symbol):
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'})
    
    user_id = session['user_id']
    result = get_max_sell_amount(symbol, user_id)
    return jsonify(result)

@app.route('/calculate_exchange/<from_currency>/<to_currency>/<amount>')
def calculate_exchange_route(from_currency, to_currency, amount):
    try:
        amount_float = float(amount)
        
        if from_currency == 'FC' and to_currency != 'FC':
            currency = Currency.query.filter_by(symbol=to_currency).first()
            if not currency:
                return jsonify({'success': False, 'message': 'Currency not found'})
            
            currency_amount = ExchangeSystem.calculate_buy_amount(currency, amount_float)
            price_impact = ExchangeSystem.get_price_impact(currency, amount_float, is_buy=True)
            
            return jsonify({
                'success': True,
                'from_amount': amount_float,
                'to_amount': currency_amount,
                'price': amount_float / currency_amount if currency_amount > 0 else 0,
                'price_impact': price_impact,
                'type': 'buy'
            })
        
        elif to_currency == 'FC' and from_currency != 'FC':
            currency = Currency.query.filter_by(symbol=from_currency).first()
            if not currency:
                return jsonify({'success': False, 'message': 'Currency not found'})
            
            fc_amount = ExchangeSystem.calculate_sell_amount(currency, amount_float)
            price_impact = ExchangeSystem.get_price_impact(currency, amount_float, is_buy=False)
            
            return jsonify({
                'success': True,
                'from_amount': amount_float,
                'to_amount': fc_amount,
                'price': fc_amount / amount_float if amount_float > 0 else 0,
                'price_impact': price_impact,
                'type': 'sell'
            })
        
        else:
            return jsonify({'success': False, 'message': 'Unsupported exchange type'})
    
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/history')
def history():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user = db.session.get(User, session['user_id'])
    if not user:
        return redirect(url_for('login'))
    
    transactions = Transaction.query.filter_by(user_id=user.id).order_by(Transaction.timestamp.desc()).limit(50).all()
    exchange_transactions = ExchangeTransaction.query.filter_by(user_id=user.id).order_by(ExchangeTransaction.timestamp.desc()).limit(50).all()
    
    return render_template('history.html', user=user, transactions=transactions, exchange_transactions=exchange_transactions)

def create_system_user():
    system_user = User.query.filter_by(user_id=SYSTEM_ID).first()
    if not system_user:
        password_hash = generate_password_hash(SYSTEM_PASSWORD)
        
        system_user = User(
            user_id=SYSTEM_ID,
            username=SYSTEM_USERNAME,
            email=SYSTEM_EMAIL,
            password_hash=password_hash,
            display_name=SYSTEM_DISPLAY_NAME,
            balance=SYSTEM_BALANCE
        )
        
        system_user.avatar_path = generate_avatar(SYSTEM_ID)
        
        db.session.add(system_user)
        db.session.commit()
        print("System user created successfully!")

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        create_system_user()
    app.run(debug=True)