from setuptools import setup


setup(
    name='grow-ext-kintaro',
    version='1.0.4',
    license='MIT',
    author='Grow Authors',
    author_email='hello@grow.io',
    include_package_data=False,
    packages=[
        'kintaro',
    ],
    install_requires=[
        'google-api-python-client==1.6.2',
    ],
)
