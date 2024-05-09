// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import {CfnOutput, Stack, StackProps, Duration, RemovalPolicy} from "aws-cdk-lib";
import {Construct} from "constructs";
import {Function, Runtime, Code} from "aws-cdk-lib/aws-lambda";
import * as iam from 'aws-cdk-lib/aws-iam';
import { loadSSMParams } from '../lib/infrastructure/ssm-params-util';
import { NagSuppressions } from 'cdk-nag'
import * as S3 from "aws-cdk-lib/aws-s3";
import * as S3Deployment from "aws-cdk-lib/aws-s3-deployment";
import path = require('path');
import * as events from "aws-cdk-lib/aws-events";
import * as targets from "aws-cdk-lib/aws-events-targets";
const {parseS3BucketNameFromUri} = require('../lib/common/utility');

const configParams = require('../config.params.json');

export class CdkBackendStack extends Stack {

  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);

    NagSuppressions.addStackSuppressions(this, [
      {
        id: 'AwsSolutions-IAM4',
        reason: 'This is the default Lambda Execution Policy which just grants writes to CloudWatch.'
      },
      {
        id: 'AwsSolutions-L1',
        reason: 'This a CDK BucketDeployment which spins up a custom resource lambda...we have no control over the pythong version it deploys'
      },{
        id: 'AwsSolutions-IAM5',
        reason: 'This a CDK BucketDeployment which spins up a custom resource lambda...we have no control over the policy it builds.  This is only used to deploy static files and these templates are only used internally to generate sample test data.'
      }
    ])

    const ssmParams = loadSSMParams(this);

    // Templates Bucket
    const templatesBucket = new S3.Bucket(this, "templatesBucket", {
      objectOwnership: S3.ObjectOwnership.BUCKET_OWNER_PREFERRED,
      removalPolicy: RemovalPolicy.DESTROY,
      encryption: S3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      blockPublicAccess: S3.BlockPublicAccess.BLOCK_ALL,
      autoDeleteObjects: true
    });

    NagSuppressions.addResourceSuppressions(templatesBucket, [
        {
          id: 'AwsSolutions-S1',
          reason: 'This is a bucket to store template data and will not be accessed by the public.  These templates are used to create test AppFabric logs and will not be used for production work.'
        },
    ])

    const bucketDeployment = new S3Deployment.BucketDeployment(this, "Deployment", {
      sources: [S3Deployment.Source.asset('lib/templates/')],
      destinationBucket: templatesBucket,
    });

    const logGeneratorLambda = new Function(this, 'logGeneratorLambda', {
      description: "App Fabric Sample Log Generator. Created By CDK AppFabric Solution. DO NOT EDIT",
      runtime: Runtime.PYTHON_3_11,
      code: Code.fromAsset(path.join(__dirname, 'lambdas/handlers/logGenerator')),
      environment: {
        APPLICATION_VERSION: `v${this.node.tryGetContext('application_version')} (${new Date().toISOString()})`,
        TEMP_BUCKET_NAME: templatesBucket.bucketName,
        APPFABRIC_BUCKET_NAME: parseS3BucketNameFromUri(ssmParams.appFabricDataSourceS3URI),
        APPFABRIC_FIREHOSE_ARN: ssmParams.kinesisFirehoseARN,
      },
      handler: 'logGenerator.handler',
      memorySize: 1028,
      reservedConcurrentExecutions: 1,
      timeout: Duration.seconds(120),
    });

    const statements = [];
    if (ssmParams.appFabricDataSourceS3URI !== 'not-defined') {
      statements.push(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: [  
            "s3:PutObject",         
            "s3:GetObject",
            "s3:ListBucket"
          ],
          resources: [
            templatesBucket.bucketArn,
            `${templatesBucket.bucketArn}/*`,
            `arn:aws:s3:::${parseS3BucketNameFromUri(ssmParams.appFabricDataSourceS3URI)}`,
            `arn:aws:s3:::${parseS3BucketNameFromUri(ssmParams.appFabricDataSourceS3URI)}/*`
          ]
        })
      )
    }
    if (ssmParams.kinesisFirehoseARN !== 'not-defined') {
      statements.push(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: [                
            "firehose:PutRecord",
            "firehose:PutRecordBatch",
          ],
          resources: [
            `${ssmParams.kinesisFirehoseARN}`
          ]
        })
      )
    }
    //Example policy for Lambda
    logGeneratorLambda.role?.attachInlinePolicy(new iam.Policy(this, 'logGeneratorLambdaPolicy', {
        statements
    }));

     // Give EventBridge permissions to invoke the Lambda function
     logGeneratorLambda.grantInvoke(new iam.ServicePrincipal('events.amazonaws.com'));

     // Create a rule to trigger the Lambda function daily at 12 midnight EST
     const logGeneratorEventRule = new events.Rule(this, 'DailyLambdaTrigger', {
       schedule: events.Schedule.expression('cron(0 0 * * ? *)'), // Runs daily at 12 midnight GMT (00:00 UTC)
     });
 
     // Add the Lambda function as a target to the rule
     logGeneratorEventRule.addTarget(new targets.LambdaFunction(logGeneratorLambda));
 
 

    /**************************************************************************************************************
      * CDK Outputs *
    **************************************************************************************************************/

    new CfnOutput(this, "TemplatesBucketName", {
      value: templatesBucket.bucketName,
    });

    new CfnOutput(this, "logGeneratorLambdaName", {
      value: logGeneratorLambda.functionName
    });

    new CfnOutput(this, "logGeneratorLambdaARN", {
      value: logGeneratorLambda.functionArn
    });

    new CfnOutput(this, "logGeneratorEventRule", {
      value: logGeneratorEventRule.ruleArn
    });

  }
}
