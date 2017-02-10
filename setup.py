import os
from setuptools import setup, find_packages


try:
    with open(os.path.join(os.path.dirname(__file__), 'README.rst'), encoding='utf-8') as f:
        long_description = f.read()
except:
    long_description = ''


setup(
    name='pretix-sepadebit',
    version='1.0.2',
    description='This plugin adds SEPA direct debit support to pretix',
    long_description=long_description,
    url='https://github.com/pretix/pretix-sepadebit',
    author='Raphael Michel',
    author_email='mail@raphaelmichel.de',
    license='Apache Software License',

    install_requires=['django-localflavor', 'sepadd>=1.1.0'],
    packages=find_packages(exclude=['tests', 'tests.*']),
    include_package_data=True,
    entry_points="""
[pretix.plugin]
pretix_sepadebit=pretix_sepadebit:PretixPluginMeta
""",
)
