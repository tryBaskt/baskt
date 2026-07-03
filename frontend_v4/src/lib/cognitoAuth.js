import {
  AuthenticationDetails,
  CognitoUser,
  CognitoUserPool,
} from "amazon-cognito-identity-js";
import { cognitoConfig } from "../authConfig";

const userPool = new CognitoUserPool({
  UserPoolId: cognitoConfig.userPoolId,
  ClientId: cognitoConfig.userPoolWebClientId,
});

function tokensFromSession(session) {
  return {
    idToken: session.getIdToken().getJwtToken(),
    accessToken: session.getAccessToken().getJwtToken(),
    refreshToken: session.getRefreshToken().getToken(),
  };
}

export function signIn(email, password) {
  const authDetails = new AuthenticationDetails({
    Username: email,
    Password: password,
  });
  const user = new CognitoUser({ Username: email, Pool: userPool });

  return new Promise((resolve, reject) => {
    user.authenticateUser(authDetails, {
      onSuccess: (session) => resolve(tokensFromSession(session)),
      onFailure: reject,
      newPasswordRequired: (userAttributes, requiredAttributes) => {
        const error = new Error("New password required.");
        error.name = "NewPasswordRequired";
        error.cognitoUser = user;
        error.userAttributes = userAttributes;
        error.requiredAttributes = requiredAttributes;
        reject(error);
      },
    });
  });
}

export function completeNewPassword(cognitoUser, newPassword, userAttributes = {}) {
  const attributes = { ...userAttributes };
  delete attributes.email;
  delete attributes.email_verified;
  delete attributes.phone_number;
  delete attributes.phone_number_verified;

  return new Promise((resolve, reject) => {
    cognitoUser.completeNewPasswordChallenge(newPassword, attributes, {
      onSuccess: (session) => resolve(tokensFromSession(session)),
      onFailure: reject,
    });
  });
}
