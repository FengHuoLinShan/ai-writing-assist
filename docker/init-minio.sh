#!/bin/sh

set -eu
umask 077

alias_name=local
endpoint=${MINIO_ENDPOINT_URL:-http://minio:9000}
case "$endpoint" in
    http://minio:9000|http://127.0.0.1:9000) ;;
    *)
        echo "MinIO initializer endpoint is not permitted." >&2
        exit 1
        ;;
esac

create_private_bucket() {
    bucket=$1
    quota=$2
    mc mb --ignore-existing "$alias_name/$bucket"
    mc anonymous set none "$alias_name/$bucket"
    mc version enable "$alias_name/$bucket"
    mc quota set "$alias_name/$bucket" --size "$quota"
}

validate_bucket_name() {
    bucket=$1
    case "$bucket" in
        ""|.*|*.|-*|*-|*..*|*.-*|*-.*|*[!a-z0-9.-]*)
            echo "MinIO bucket names must be lowercase DNS-style names." >&2
            exit 1
            ;;
    esac
    if [ "${#bucket}" -lt 3 ] || [ "${#bucket}" -gt 63 ]; then
        echo "MinIO bucket names must contain 3 to 63 characters." >&2
        exit 1
    fi
}

validate_bucket_name "$MAP_ATLAS_S3_BUCKET"
validate_bucket_name "$WORLD_OBJECT_S3_BUCKET"
if [ "$MAP_ATLAS_S3_BUCKET" = "$WORLD_OBJECT_S3_BUCKET" ]; then
    echo "MinIO buckets must be distinct." >&2
    exit 1
fi

case "$MINIO_APP_ACCESS_KEY:$MINIO_APP_SECRET_KEY" in
    :*|*:)
        echo "MinIO application credentials are required." >&2
        exit 1
        ;;
esac
case "$MINIO_APP_ACCESS_KEY" in
    *[!A-Za-z0-9_-]*)
        echo "MinIO application access key contains unsafe characters." >&2
        exit 1
        ;;
esac

mc alias set "$alias_name" "$endpoint" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"

# The two bucket quotas are intentionally the whole single-disk object-data cap.
create_private_bucket "$MAP_ATLAS_S3_BUCKET" 8GiB
create_private_bucket "$WORLD_OBJECT_S3_BUCKET" 24GiB

cat > /tmp/world-object-storage-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetBucketLocation", "s3:ListBucket", "s3:ListBucketVersions"],
      "Resource": ["arn:aws:s3:::$MAP_ATLAS_S3_BUCKET", "arn:aws:s3:::$WORLD_OBJECT_S3_BUCKET"]
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:DeleteObjectVersion"],
      "Resource": ["arn:aws:s3:::$MAP_ATLAS_S3_BUCKET/*", "arn:aws:s3:::$WORLD_OBJECT_S3_BUCKET/*"]
    }
  ]
}
EOF
mc admin policy create "$alias_name" world-object-storage \
    /tmp/world-object-storage-policy.json
mc admin user add "$alias_name" "$MINIO_APP_ACCESS_KEY" "$MINIO_APP_SECRET_KEY"
mc admin policy attach "$alias_name" world-object-storage --user "$MINIO_APP_ACCESS_KEY"
