from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Table
from sqlalchemy.orm import relationship, backref
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.exc import OperationalError
import datetime

def get_or_create(session, model, **kwargs):
    instance = session.query(model).filter_by(**kwargs).first()
    if instance:
        return instance
    else:
        instance = model(**kwargs)
        session.add(instance)
        session.commit()
        return instance

def delete_all_data(session):
    # Delete primary tables
    tables = [Endpoint, Parameter, ProductGroup, Product, Template, Header]

    for table in tables:
        try:
            session.query(table).delete()
            session.commit()
        except OperationalError:
            continue

    # Delete association tables
    tables = [EndpointParameter, EndpointTemplate, EndpointHeader]

    for table in tables:
        session.execute(table.delete())
        session.commit()

    print("All of the database's tables have been cleared")

Base = declarative_base()

EndpointParameter = Table('endpoint_parameter', Base.metadata,
    Column('endpointId', Integer, ForeignKey('endpoint.id')),
    Column('parameterId', Integer, ForeignKey('parameter.id'))
)

EndpointTemplate = Table('endpoint_template', Base.metadata,
    Column('endpointId', Integer, ForeignKey('endpoint.id')),
    Column('templateId', Integer, ForeignKey('template.id'))
)

EndpointHeader = Table('endpoint_header', Base.metadata,
    Column('endpointId', Integer, ForeignKey('endpoint.id')),
    Column('headerId', Integer, ForeignKey('header.id'))
)


class Endpoint(Base):
    __tablename__ = 'endpoint'
    id = Column(Integer, primary_key=True)
    baseUrl = Column(String)
    endpoint = Column(String)
    method = Column(String)
    plugin = Column(String)
    filepath = Column(String)
    lineNumber = Column(Integer)
    regex = Column(Boolean)
    private = Column(Boolean)
    createdDate = Column(DateTime, default=datetime.datetime.utcnow)
    touchedDate = Column(DateTime, default=datetime.datetime.utcnow)
    productId = Column(Integer, ForeignKey('product.id'))
    parameters = relationship('Parameter', secondary=EndpointParameter,
                              backref=backref('endpoints', cascade='all'),
                              lazy=False)
    templates = relationship('Template', secondary=EndpointTemplate,
                             backref=backref('endpoints', cascade='all'),
                             lazy=False)
    headers = relationship('Header', secondary=EndpointHeader,
                           backref=backref('endpoints', cascade='all'),
                           lazy=False)

    def __repr__(self):
        return "<Endpoint {}>".format(self.baseUrl.rstrip('/') + '/' +
                                      self.endpoint.lstrip('/'))

    def to_dict(self):
        return {
            'url': self.baseUrl.rstrip('/') + '/' + self.endpoint.lstrip('/'),
            'method': None if self.method == "None" else self.method,
            'filepath': self.filepath,
            'lineNumber': self.lineNumber,
            'plugin': self.plugin,
            'createdDate': self.createdDate,
            'productGroup': self.product.productGroup.name,
            'gitRepo': self.product.gitRepo,
            'product': self.product.name,
            'params': list(map(lambda x: {
                'name': x.name,
                'filepath': x.filepath,
                'lineNumber': x.lineNumber
                }, self.parameters)),
            'templates': list(map(lambda x: x.filepath, self.templates)),
            'headers': list(map(lambda x: {'name': x.value.split(': ')[0],
                                           'value': x.value.split(': ')[1]}, self.headers))
        }


class Parameter(Base):
    __tablename__ = 'parameter'
    id = Column(Integer, primary_key=True)
    name = Column(String)
    filepath = Column(String)
    lineNumber = Column(Integer)
    # These need to be here because a project could copy source code
    productId = Column(Integer, ForeignKey('product.id'))
    product = relationship('Product', backref='parameters', lazy=False)

    def __repr__(self):
        return "<Parameter {}>".format(self.name)


class ProductGroup(Base):
    __tablename__ = 'productgroup'
    id = Column(Integer, primary_key=True)
    name = Column(String)
    products = relationship('Product', backref='productGroup',
                            cascade="all, delete-orphan", lazy=False)

    def __repr__(self):
        return "<ProductGroup {}>".format(self.name)


class Product(Base):
    __tablename__ = 'product'
    id = Column(Integer, primary_key=True)
    name = Column(String)
    gitRepo = Column(String)
    productGroupId = Column(Integer, ForeignKey('productgroup.id'))
    endpoints = relationship('Endpoint', backref='product', lazy=False)

    def __repr__(self):
        return "<Product {}>".format(self.name)


class Template(Base):
    __tablename__ = 'template'
    id = Column(Integer, primary_key=True)
    filepath = Column(String)
    # These need to be here because a project could copy source code
    productId = Column(Integer, ForeignKey('product.id'))
    product = relationship('Product', backref='templates', lazy=False)

    def __repr__(self):
        return "<Template {}>".format(self.filepath)

class Header(Base):
    __tablename__ = 'header'
    id = Column(Integer, primary_key=True)
    value = Column(String)

    def __repr__(self):
        return "<Header {}>".format(self.value)
