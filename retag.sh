#!/usr/bin/env bash

git tag -d 0.13.6
git push --delete origin 0.13.6
git tag 0.13.6
git push --tags
