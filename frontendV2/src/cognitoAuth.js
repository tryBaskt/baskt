import { AuthenticationDetails, CognitoUserPool, CognitoUser } from "amazon-cognito-identity-js";
import { cognitoConfig } from "./authConfig";

const userPool = new CognitoUserPool({
  UserPoolId: cognitoConfig.userPoolId,
  ClientId: cognitoConfig.userPoolWebClientId,
});

export function signUp(email, password) {
  return new Promise((resolve, reject) => {
    userPool.signUp(
      email,
      password,
      [{ Name: "email", Value: email }],
      null,
      (err, result) => {
        if (err) {
          reject(err);
          return;
        }
        resolve(result);
      }
    );
  });
}

export function confirmSignUp(email, code) {
  const user = new CognitoUser({ Username: email, Pool: userPool });

  return new Promise((resolve, reject) => {
    user.confirmRegistration(code, true, (err, result) => {
      if (err) {
        reject(err);
        return;
      }
      resolve(result);
    });
  });
}

export function signIn(email, password) {
  const authDetails = new AuthenticationDetails({
    Username: email,
    Password: password,
  });
  const user = new CognitoUser({ Username: email, Pool: userPool });

  return new Promise((resolve, reject) => {
    user.authenticateUser(authDetails, {
      onSuccess: (session) => {
        resolve({
          idToken: session.getIdToken().getJwtToken(),
          accessToken: session.getAccessToken().getJwtToken(),
          refreshToken: session.getRefreshToken().getToken(),
        });
      },
      onFailure: (err) => reject(err),
      newPasswordRequired: () => reject(new Error("New password required.")),
    });
  });
}
