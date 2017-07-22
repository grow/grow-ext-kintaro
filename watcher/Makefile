project ?= grow-prod
app_identity_email ?= $(project)@appspot.gserviceaccount.com
app_identity_key_path ?= key.pem

create-app-identity-key:
	gcloud iam service-accounts keys create \
		key.p12 \
		--key-file-type=p12 \
		--iam-account $(app_identity_email)
	cat key.p12 | \
		openssl pkcs12 -nodes -nocerts -passin pass:notasecret | \
		openssl rsa > key.pem
	rm key.p12

deploy-app:
	gcloud app deploy \
	  -q \
	  --project=$(project) \
	  app.yaml

deploy-cron:
	gcloud app deploy \
	  -q \
	  --project=$(project) \
	  cron.yaml

install:
	pip install -t lib -r requirements.txt

run:
	dev_appserver.py \
		--appidentity_email_address $(app_identity_email) \
    --appidentity_private_key_path $(app_identity_key_path) \
		app.yaml
